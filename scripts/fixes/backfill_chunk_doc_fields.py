#!/usr/bin/env python3
"""Backfill doc-level attributes onto chunk payloads so Heatmapper *query mode*
filters them correctly.

Heatmapper has two modes:

  * Attribute mode (no search string) counts documents — it resolves filters
    against the PostgreSQL docs table / Qdrant document collection.
  * Query mode (with a search string) searches *chunks* and filters on the chunk
    payload.

A few attributes are doc-level and were only *sparsely* denormalised onto chunks
(verified: ~25/300 chunks carried ``src_evaluation_category`` /
``src_quality_rating``, ~2/300 carried ``map_region``). So a query-mode map of,
say, "evaluation category x year" with a search string dropped most documents —
every chunk whose payload lacked the value was filtered out.

This script reads each document's authoritative value from PostgreSQL
(``docs_<source>``) and stamps it onto *all* of that document's chunks in Qdrant
(``chunks_<source>``), so the chunk filter matches the same documents the facet
counts do.

  Source of truth (PostgreSQL ``docs_<source>``):
    - ``map_*``  fields  -> the mapped column (e.g. ``map_region``)
    - ``src_*``  fields  -> ``src_doc_raw_metadata->>'<raw key>'`` (raw key from
                            the data source's ``src_field_mapping``)
  Target (Qdrant ``chunks_<source>``):
    - the same field name as a per-chunk payload key

Safety rails (mirrors scripts/fixes/fix_wfp_metadata_deltas.py):
  * Dry-run by default — nothing is written without ``--apply``.
  * Never nulls a value: documents with no value for a field are skipped, so a
    chunk is only ever *given* a value, never cleared.
  * Idempotent — only chunks whose payload does not already equal the target are
    written (a ``must_not`` match on the value), so re-runs are no-ops.
  * Writes are batched by value: all documents sharing a value are updated in one
    ``set_payload`` call (e.g. 3 calls for DE/CE/IE), keeping Qdrant load low.

Usage:
    # Dry-run (default): report what would change, write nothing
    python scripts/fixes/backfill_chunk_doc_fields.py --data-source wfp

    # Apply for real
    python scripts/fixes/backfill_chunk_doc_fields.py --data-source wfp --apply

    # Limit to specific fields
    python scripts/fixes/backfill_chunk_doc_fields.py --data-source wfp \
        --fields src_evaluation_category map_region
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, namedtuple
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Doc-level fields that are only sparsely present on chunks (measured) and so
# break Heatmapper query mode until backfilled. ``src_*`` fields resolve their
# value from the raw JSONB; ``map_*`` fields from the mapped column.
DEFAULT_FIELDS = [
    "src_evaluation_category",
    "src_quality_rating",
    "map_region",
]

_IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*")

# field        = chunk payload key (also the docs_<source> column for map_*)
# kind         = "column" (read a docs column) | "jsonb" (read src_doc_raw_metadata)
# source_key   = column name, or raw JSONB key for src_* fields
FieldSpec = namedtuple("FieldSpec", "field kind source_key")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB / Qdrant)
# ---------------------------------------------------------------------------


def resolve_source(config: Dict[str, Any], source: str) -> Tuple[str, Dict[str, Any]]:
    """Resolve a data-source key or subdir against the config whitelist."""
    for key, block in config.get("datasources", {}).items():
        if key == source or block.get("data_subdir") == source:
            return block.get("data_subdir", source), block
    raise SystemExit(f"Unknown data_source: {source!r} (not in config.json)")


def build_field_specs(block: Dict[str, Any], requested: List[str]) -> List[FieldSpec]:
    """Resolve each requested field to where its authoritative value is read.

    ``src_*`` fields need a configured ``src_field_mapping`` entry (the raw JSONB
    key); a field without one is skipped with a warning rather than crashing.
    """
    src_map = block.get("src_field_mapping", {})
    specs: List[FieldSpec] = []
    for field in requested:
        if not _IDENT_RE.fullmatch(field):
            raise SystemExit(f"Illegal field name: {field!r}")
        if field.startswith("src_"):
            raw_key = src_map.get(field)
            if not raw_key:
                logger.warning("No src_field_mapping for %s; skipping it", field)
                continue
            specs.append(FieldSpec(field, "jsonb", raw_key))
        else:
            specs.append(FieldSpec(field, "column", field))
    return specs


def group_doc_ids_by_value(
    rows: List[Dict[str, Any]], field: str
) -> Dict[str, List[str]]:
    """Map each non-empty value of ``field`` to the doc_ids that hold it.

    Documents with no value are skipped (never written), and values are trimmed
    so a stray-whitespace variant does not become its own group.
    """
    groups: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        groups[text].append(row["doc_id"])
    return dict(groups)


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _postgres_conn():
    import psycopg2  # local import — keeps the import lazy

    try:
        from pipeline.db.postgres_client_base import build_postgres_dsn

        dsn = build_postgres_dsn()
    except ImportError:
        dsn = (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"user={os.environ.get('POSTGRES_USER', 'evidencelab')} "
            f"password={os.environ.get('POSTGRES_PASSWORD', 'evidencelab')} "
            f"dbname={os.environ.get('POSTGRES_DB', 'evidencelab')}"
        )
    return psycopg2.connect(dsn)


def fetch_doc_values(conn, table: str, specs: List[FieldSpec]) -> List[Dict[str, Any]]:
    """Fetch each doc's authoritative value for every spec'd field.

    Column names are validated identifiers (interpolated); JSONB keys are passed
    as bound parameters, so no user value is interpolated into the SQL string.
    """
    select_parts = ["doc_id"]
    params: List[str] = []
    for spec in specs:
        if spec.kind == "column":
            select_parts.append(spec.source_key)  # validated identifier
        else:
            select_parts.append("src_doc_raw_metadata->>%s")
            params.append(spec.source_key)
    query = f"SELECT {', '.join(select_parts)} FROM {table}"  # nosec B608
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        record: Dict[str, Any] = {"doc_id": str(row[0])}
        for idx, spec in enumerate(specs):
            record[spec.field] = row[1 + idx]
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _qdrant_client():
    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    host = host.replace("://qdrant:", "://localhost:")
    # A filter-scoped set_payload can touch tens of thousands of chunks server
    # side; the default 5s client timeout fires long before it finishes, so give
    # it plenty of headroom (override with QDRANT_TIMEOUT if needed).
    timeout = int(os.getenv("QDRANT_TIMEOUT", "600"))
    return QdrantClient(url=host, api_key=os.getenv("QDRANT_API_KEY"), timeout=timeout)


def _missing_filter(doc_ids: List[str], field: str, value: str):
    """Chunks in ``doc_ids`` whose ``field`` does not already equal ``value``."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    return Filter(
        must=[FieldCondition(key="doc_id", match=MatchAny(any=doc_ids))],
        must_not=[FieldCondition(key=field, match=MatchValue(value=value))],
    )


def _count_missing(client, collection: str, flt) -> int:
    return client.count(collection_name=collection, count_filter=flt, exact=True).count


def _set_payload_retry(client, collection: str, payload, flt) -> None:
    """set_payload (scoped by filter) with bounded exponential-backoff retries."""
    for attempt in range(5):
        try:
            client.set_payload(
                collection_name=collection, payload=payload, points=flt, wait=True
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry any transient Qdrant error
            wait = 2**attempt
            logger.warning(
                "Retry %d for %s: %s (sleep %ds)", attempt + 1, collection, exc, wait
            )
            time.sleep(wait)
    raise RuntimeError(f"Failed to set payload on {collection} for {payload}")


def backfill_field(
    client,
    collection: str,
    spec: FieldSpec,
    groups: Dict[str, List[str]],
    apply: bool,
) -> Tuple[int, int]:
    """Stamp ``spec.field`` onto chunks for every value group.

    Returns ``(chunks_backfilled, docs_touched)`` counted over chunks that did
    not already carry the value (so re-runs report 0).
    """
    chunks_total = 0
    docs_total = 0
    for value, doc_ids in groups.items():
        flt = _missing_filter(doc_ids, spec.field, value)
        missing = _count_missing(client, collection, flt)
        if missing == 0:
            continue
        chunks_total += missing
        docs_total += len(doc_ids)
        logger.info(
            "  %s=%r: %d chunk(s) across %d doc(s)",
            spec.field,
            value,
            missing,
            len(doc_ids),
        )
        if apply:
            _set_payload_retry(client, collection, {spec.field: value}, flt)
    return chunks_total, docs_total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill doc-level attributes onto chunk payloads for "
        "Heatmapper query mode."
    )
    parser.add_argument(
        "--data-source", default="wfp", help="Data source (default: wfp)"
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        default=DEFAULT_FIELDS,
        help="Chunk payload fields to backfill (default: the sparse doc-level "
        "fields src_evaluation_category, src_quality_rating, map_region)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry-run)"
    )
    return parser.parse_args(argv)


def _load_config() -> Dict[str, Any]:
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
    config_path = os.path.join(os.path.dirname(__file__), "../../config.json")
    with open(config_path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    config = _load_config()
    subdir, block = resolve_source(config, args.data_source)
    specs = build_field_specs(block, args.fields)
    if not specs:
        raise SystemExit("No backfillable fields resolved; nothing to do.")

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("=" * 64)
    logger.info(" Chunk doc-field backfill  [%s]", mode)
    logger.info(" data_source=%s  docs_%s -> chunks_%s", subdir, subdir, subdir)
    logger.info(" fields=%s", [s.field for s in specs])
    logger.info("=" * 64)

    conn = _postgres_conn()
    try:
        rows = fetch_doc_values(conn, f"docs_{subdir}", specs)
    finally:
        conn.close()

    client = _qdrant_client()
    collection = f"chunks_{subdir}"
    total_chunks = 0
    for spec in specs:
        groups = group_doc_ids_by_value(rows, spec.field)
        docs_with_value = sum(len(v) for v in groups.values())
        logger.info(
            "%s: %d value(s), %d doc(s) with a value",
            spec.field,
            len(groups),
            docs_with_value,
        )
        chunks, _docs = backfill_field(client, collection, spec, groups, args.apply)
        total_chunks += chunks

    label = "backfilled" if args.apply else "would backfill"
    logger.info("-" * 64)
    logger.info(" Summary  [%s]", mode)
    logger.info("   chunks %s in %s: %d", label, collection, total_chunks)
    if not args.apply:
        logger.info(" Re-run with --apply to write these changes.")
    logger.info("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
