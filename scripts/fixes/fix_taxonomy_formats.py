#!/usr/bin/env python3
"""
Fix taxonomy tag values in Qdrant and PostgreSQL to match the pipeline format.

The pipeline stores taxonomy tags as "{code} - {name}" where code and name
come from config.json. Some records have an incorrect short format
(e.g., "sdg1 - No Poverty" instead of "sdg1 - SDG1 - No Poverty").

This script reads taxonomy definitions from config.json, builds a mapping
of code -> correct value, then scans Qdrant collections and PostgreSQL
tables and fixes any values that don't match the expected format.

Qdrant stores tags as string arrays in tag_* payload fields:
    ["sdg1 - SDG1 - No Poverty", "sdg2 - SDG2 - Zero Hunger"]

PostgreSQL stores tags in the sys_taxonomies JSONB column:
    {"sdg": [{"code": "sdg1", "name": "SDG1 - No Poverty", "reason": "..."}]}

Usage:
    python scripts/fixes/fix_taxonomy_formats.py --data-source uneg --dry-run
    python scripts/fixes/fix_taxonomy_formats.py --data-source uneg
    python scripts/fixes/fix_taxonomy_formats.py --data-source uneg --collection chunks
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Set, Tuple

# Add repo root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_taxonomy_mappings(
    config_path: str, data_source: str
) -> Dict[str, Dict[str, str]]:
    """
    Load taxonomy definitions from config.json and build code -> correct_value mapping.

    Taxonomies are defined per datasource at:
        datasources.<name>.pipeline.tag.taxonomies

    The data_source is matched against each datasource's data_subdir field.

    Returns:
        Dict keyed by tag field name (e.g., "tag_sdg"), values are dicts of
        code -> correct formatted string.
    """
    with open(config_path) as f:
        config = json.load(f)

    # Find the datasource config matching the data_source
    taxonomies = {}
    for ds_name, ds_config in config.get("datasources", {}).items():
        if ds_config.get("data_subdir") == data_source:
            taxonomies = (
                ds_config.get("pipeline", {}).get("tag", {}).get("taxonomies", {})
            )
            logger.info("Found taxonomies in datasource '%s'", ds_name)
            break
    else:
        logger.warning(
            "No datasource with data_subdir='%s' found in config", data_source
        )
    mappings: Dict[str, Dict[str, str]] = {}

    for tax_key, tax_config in taxonomies.items():
        field_name = f"tag_{tax_key}"
        code_to_correct: Dict[str, str] = {}

        for code, value_config in tax_config.get("values", {}).items():
            name = value_config.get("name", "")
            correct_value = f"{code} - {name}" if name else code
            code_to_correct[code] = correct_value

        if code_to_correct:
            mappings[field_name] = code_to_correct
            logger.info(
                "Loaded %d values for %s (e.g., %s)",
                len(code_to_correct),
                field_name,
                next(iter(code_to_correct.values())),
            )

    return mappings


def extract_code(value: str) -> str:
    """Extract the code prefix from a tag value (e.g., 'sdg1' from 'sdg1 - No Poverty')."""
    sep = value.find(" - ")
    return value[:sep] if sep != -1 else value


def _compute_point_updates(
    point: Any,
    tag_fields: Set[str],
    mappings: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Check a single point and return updates needed (empty dict if none)."""
    payload = point.payload or {}
    updates: Dict[str, List[str]] = {}

    for field_name in tag_fields:
        values = payload.get(field_name)
        if not values or not isinstance(values, list):
            continue

        fixed_values: List[str] = []
        field_changed = False

        for val in values:
            code = extract_code(val)
            correct_value = mappings[field_name].get(code)

            if correct_value and val != correct_value:
                fixed_values.append(correct_value)
                field_changed = True
            else:
                fixed_values.append(val)

        if field_changed:
            updates[field_name] = fixed_values

    return updates


def fix_qdrant_collection(
    db: Any,
    collection_name: str,
    mappings: Dict[str, Dict[str, str]],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Scan a Qdrant collection and fix any taxonomy values that don't match config.

    Groups points with identical payload updates into batches for efficiency.

    Returns:
        Tuple of (points_scanned, points_fixed).
    """
    logger.info("Scanning Qdrant collection: %s", collection_name)

    tag_fields: Set[str] = set(mappings.keys())
    points_scanned = 0
    points_fixed = 0
    offset = None

    # Accumulate batches: payload_key -> (payload_dict, [point_ids])
    batch: Dict[str, Tuple[Dict[str, List[str]], List[Any]]] = {}
    BATCH_FLUSH_SIZE = 500
    SUB_BATCH_SIZE = 50  # Max point IDs per set_payload call
    MAX_RETRIES = 5

    def _set_payload_with_retry(payload: Dict, points: List) -> None:
        for attempt in range(MAX_RETRIES):
            try:
                db.client.set_payload(
                    collection_name=collection_name,
                    payload=payload,
                    points=points,
                    wait=False,
                )
                return
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait_time = 2**attempt
                logger.warning(
                    "  Qdrant error (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    wait_time,
                    e,
                )
                time.sleep(wait_time)

    def flush_batch():
        nonlocal batch
        if not batch:
            return
        for _key, (payload, point_ids) in batch.items():
            for i in range(0, len(point_ids), SUB_BATCH_SIZE):
                chunk = point_ids[i : i + SUB_BATCH_SIZE]
                _set_payload_with_retry(payload, chunk)
                time.sleep(0.1)
        batch = {}

    while True:
        results, offset = db.client.scroll(
            collection_name=collection_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not results:
            break

        for point in results:
            points_scanned += 1
            updates = _compute_point_updates(point, tag_fields, mappings)

            if updates:
                points_fixed += 1

                if points_fixed <= 5:
                    payload = point.payload or {}
                    for field_name, new_vals in updates.items():
                        old_vals = payload.get(field_name, [])
                        logger.info(
                            "  Point %s %s: %s -> %s",
                            point.id,
                            field_name,
                            old_vals,
                            new_vals,
                        )

                if not dry_run:
                    # Group by identical payload for batching
                    payload_key = str(sorted(updates.items()))
                    if payload_key not in batch:
                        batch[payload_key] = (updates, [])
                    batch[payload_key][1].append(point.id)

        # Flush batch periodically
        total_pending = sum(len(ids) for _, ids in batch.values())
        if not dry_run and total_pending >= BATCH_FLUSH_SIZE:
            flush_batch()

        if offset is None:
            break

        if points_scanned % 10000 == 0:
            logger.info(
                "  Scanned %d points, fixed %d so far...",
                points_scanned,
                points_fixed,
            )

    # Final flush
    if not dry_run:
        flush_batch()

    return points_scanned, points_fixed


def fix_postgres_table(
    db: Any,
    table_name: str,
    mappings: Dict[str, Dict[str, str]],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Fix taxonomy name values in a PostgreSQL sys_taxonomies JSONB column.

    For each taxonomy key (e.g., "sdg"), rebuilds the array with corrected
    name fields using a single UPDATE statement.

    Returns:
        Tuple of (rows_with_taxonomy, rows_fixed).
    """
    logger.info("Fixing PostgreSQL table: %s", table_name)
    total_scanned = 0
    total_fixed = 0

    for tag_field, code_map in mappings.items():
        tax_key = tag_field.removeprefix("tag_")

        # Build code -> correct_name (just the name portion, not full tag string)
        # e.g., "sdg1 - SDG1 - No Poverty" -> "SDG1 - No Poverty"
        code_to_name: Dict[str, str] = {}
        for code, tag_value in code_map.items():
            sep = tag_value.find(" - ")
            code_to_name[code] = tag_value[sep + 3 :] if sep != -1 else tag_value

        # Build dynamic CASE and EXISTS clauses with %s placeholders
        case_clauses: List[str] = []
        exists_clauses: List[str] = []
        case_params: List[Any] = []
        exists_params: List[Any] = []

        for code, name in code_to_name.items():
            case_clauses.append(
                "WHEN elem->>'code' = %s "
                "THEN jsonb_set(elem, '{name}', to_jsonb(%s::text))"
            )
            case_params.extend([code, name])
            exists_clauses.append("(elem->>'code' = %s AND elem->>'name' != %s)")
            exists_params.extend([code, name])

        case_sql = " ".join(case_clauses)
        exists_sql = " OR ".join(exists_clauses)

        with db.pg._get_conn() as conn:
            with conn.cursor() as cur:
                # Count rows with this taxonomy
                cur.execute(
                    f"SELECT COUNT(*) FROM {table_name} "
                    f"WHERE sys_taxonomies->'{tax_key}' IS NOT NULL "
                    f"AND jsonb_array_length(sys_taxonomies->'{tax_key}') > 0",
                )
                scanned = cur.fetchone()[0]
                total_scanned += scanned

                # Count rows needing fix
                cur.execute(
                    f"SELECT COUNT(*) FROM {table_name} "
                    f"WHERE sys_taxonomies->'{tax_key}' IS NOT NULL "
                    f"AND EXISTS ("
                    f"  SELECT 1 FROM jsonb_array_elements("
                    f"sys_taxonomies->'{tax_key}') AS elem "
                    f"  WHERE {exists_sql}"
                    f")",
                    exists_params,
                )
                to_fix = cur.fetchone()[0]

                logger.info(
                    "  %s.sys_taxonomies['%s']: %d rows total, %d need fixing",
                    table_name,
                    tax_key,
                    scanned,
                    to_fix,
                )

                if to_fix == 0:
                    continue

                # Log sample before/after
                cur.execute(
                    f"SELECT elem->>'code', elem->>'name' "
                    f"FROM {table_name}, "
                    f"jsonb_array_elements(sys_taxonomies->'{tax_key}') AS elem "
                    f"WHERE {exists_sql} LIMIT 3",
                    exists_params,
                )
                for row in cur.fetchall():
                    correct = code_to_name.get(row[0], row[1])
                    logger.info(
                        "  Sample: %s name '%s' -> '%s'", row[0], row[1], correct
                    )

                if dry_run:
                    total_fixed += to_fix
                    continue

                # Single UPDATE: rebuild the taxonomy array with corrected names
                cur.execute(
                    f"UPDATE {table_name} SET sys_taxonomies = jsonb_set("
                    f"  sys_taxonomies,"
                    f"  ARRAY['{tax_key}']::text[],"
                    f"  (SELECT jsonb_agg("
                    f"    CASE {case_sql} ELSE elem END"
                    f"  ) FROM jsonb_array_elements("
                    f"sys_taxonomies->'{tax_key}') AS elem)"
                    f") "
                    f"WHERE sys_taxonomies->'{tax_key}' IS NOT NULL "
                    f"AND EXISTS ("
                    f"  SELECT 1 FROM jsonb_array_elements("
                    f"sys_taxonomies->'{tax_key}') AS elem "
                    f"  WHERE {exists_sql}"
                    f")",
                    case_params + exists_params,
                )
                rows_updated = cur.rowcount
                conn.commit()
                total_fixed += rows_updated
                logger.info(
                    "  Updated %d rows in %s for taxonomy '%s'",
                    rows_updated,
                    table_name,
                    tax_key,
                )

    return total_scanned, total_fixed


def main():
    parser = argparse.ArgumentParser(
        description="Fix taxonomy tag formats in Qdrant and PostgreSQL to match config.json"
    )
    parser.add_argument(
        "--data-source",
        required=True,
        help="Data source name (e.g., uneg)",
    )
    parser.add_argument(
        "--collection",
        choices=["both", "documents", "chunks"],
        default="both",
        help="Which collection(s) to fix (default: both)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (default: config.json)",
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Load taxonomy definitions from config
    mappings = load_taxonomy_mappings(args.config, args.data_source)
    if not mappings:
        logger.error("No taxonomy definitions found in config")
        sys.exit(1)

    db = get_db(args.data_source)

    # --- Qdrant ---
    logger.info("=" * 60)
    logger.info("QDRANT")
    logger.info("=" * 60)

    qdrant_scanned = 0
    qdrant_fixed = 0

    collections = []
    if args.collection in ("both", "documents"):
        collections.append(db.documents_collection)
    if args.collection in ("both", "chunks"):
        collections.append(db.chunks_collection)

    for collection_name in collections:
        scanned, fixed = fix_qdrant_collection(
            db, collection_name, mappings, args.dry_run
        )
        qdrant_scanned += scanned
        qdrant_fixed += fixed
        logger.info(
            "Qdrant %s: scanned %d points, fixed %d",
            collection_name,
            scanned,
            fixed,
        )

    # --- PostgreSQL ---
    logger.info("=" * 60)
    logger.info("POSTGRESQL")
    logger.info("=" * 60)

    pg_scanned = 0
    pg_fixed = 0

    pg_tables = []
    if args.collection in ("both", "documents"):
        pg_tables.append(db.pg.docs_table)
    if args.collection in ("both", "chunks"):
        pg_tables.append(db.pg.chunks_table)

    for table_name in pg_tables:
        scanned, fixed = fix_postgres_table(db, table_name, mappings, args.dry_run)
        pg_scanned += scanned
        pg_fixed += fixed
        logger.info(
            "PostgreSQL %s: %d rows with taxonomies, %d fixed",
            table_name,
            scanned,
            fixed,
        )

    # --- Summary ---
    logger.info("=" * 60)
    action = "Would fix" if args.dry_run else "Fixed"
    logger.info(
        "%s: Qdrant %d/%d points, PostgreSQL %d/%d rows",
        action,
        qdrant_fixed,
        qdrant_scanned,
        pg_fixed,
        pg_scanned,
    )


if __name__ == "__main__":
    main()
