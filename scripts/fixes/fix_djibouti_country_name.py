#!/usr/bin/env python3
"""
Fix the misspelled country token 'Dibouti' -> 'Djibouti' across the country
metadata fields in PostgreSQL and Qdrant.

Country values are stored as ``'; '``-separated lists (e.g.
``'Chad; Honduras; State of Palestine; United Arab Emirates; Dibouti; Nepal'``).
This script tokenises each value, replaces an exact token ``'Dibouti'`` with
``'Djibouti'``, and rejoins. Existing correct ``'Djibouti'`` tokens are left
untouched (idempotent), and because ``'Dibouti'`` is not a substring of
``'Djibouti'`` the matching never touches already-correct values.

Scope (verified against docs_wfp / chunks_wfp on 2026-06-30):

  A single document carries the typo:
    doc_id = 201f6a29-12a6-55a8-860c-041116041af6
    title  = "Evaluation of WFP's Supply Chain Strategic Roadmap (2022-2025)"
    value  = "Chad; Honduras; State of Palestine; United Arab Emirates; Dibouti; Nepal"

  PostgreSQL:
    - docs_wfp.map_country                       (text column, 1 row)
    - docs_wfp.src_doc_raw_metadata->>'Country'  (JSONB string, 1 row)

  Qdrant:
    - documents_wfp.map_country  (payload string, 1 point)
    - chunks_wfp.map_country     (payload string, 247 points — all chunks of
                                  the one document)

Out of scope — intentionally NOT touched:
  - chunks_<source> Postgres tables: have no country column / key.
  - The empty documents_wfp_evaluation_reports / chunks_wfp_evaluation_reports
    collections (a different, unused data source).
  - Any other field in any other collection / table.

Why the typo is visible in the heatmapper but not the regular search filter:
  Both read the same ``map_country`` field. The heatmapper / filter-only path
  (``build_facets_from_db``) facets over the *entire* documents collection and
  splits each ``'; '``-separated value into individual country tokens, so
  ``'Dibouti'`` surfaces as its own row. The regular-search facet path
  (``get_search_facets``) only aggregates countries from the documents matching
  the active query (top ~500 chunk hits), so the single mis-tagged document does
  not appear and typing "dib" yields nothing. Fixing the data resolves both.

Usage:
    # Default — dry-run, no writes:
    python scripts/fixes/fix_djibouti_country_name.py --data-source wfp

    # Apply the fix for real:
    python scripts/fixes/fix_djibouti_country_name.py --data-source wfp --apply
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from qdrant_client import QdrantClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

OLD_TOKEN = "Dibouti"
NEW_TOKEN = "Djibouti"
SEPARATOR = "; "


def rewrite_country(value):
    """Replace the exact token ``Dibouti`` with ``Djibouti``.

    Accepts either:
      - a ``'; '``-separated string; tokens are split, exact-match rewritten,
        and rejoined.
      - a list of strings (some Qdrant payloads store countries as a list);
        each element is rewritten if it equals ``'Dibouti'``.

    Returns the input unchanged if no rewrite is needed (idempotent).
    Other types (``None``, dicts, numbers) pass through unchanged.
    """
    if isinstance(value, str):
        if not value:
            return value
        tokens = value.split(SEPARATOR)
        rewritten = [NEW_TOKEN if tok.strip() == OLD_TOKEN else tok for tok in tokens]
        new = SEPARATOR.join(rewritten)
        return new if new != value else value
    if isinstance(value, list):
        rewritten = [
            NEW_TOKEN if isinstance(item, str) and item.strip() == OLD_TOKEN else item
            for item in value
        ]
        return rewritten if rewritten != value else value
    return value


def needs_rewrite(value) -> bool:
    return value is not None and rewrite_country(value) != value


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def fix_postgres(conn, data_source: str, apply: bool) -> Dict[str, int]:
    """Fix docs_<source>.map_country and src_doc_raw_metadata->>'Country'.

    Returns a dict of {phase: count_of_rows_changed}.
    """
    table = f"docs_{data_source}"
    stats = {"map_country_rows": 0, "raw_metadata_rows": 0}

    with conn.cursor() as cur:
        # Pass 1: map_country column
        cur.execute(
            f"SELECT doc_id, map_country FROM {table} "
            f"WHERE map_country IS NOT NULL AND map_country LIKE %s",
            (f"%{OLD_TOKEN}%",),
        )
        rows = cur.fetchall()
        column_changes: List[Tuple[str, str, str]] = []
        for doc_id, val in rows:
            if needs_rewrite(val):
                column_changes.append((doc_id, val, rewrite_country(val)))
        logger.info(
            "[PG] %s.map_country: %d rows match '%%%s%%', %d need rewrite",
            table,
            len(rows),
            OLD_TOKEN,
            len(column_changes),
        )
        for doc_id, old, new in column_changes:
            logger.info("  doc=%s  %r -> %r", doc_id, old, new)
        stats["map_country_rows"] = len(column_changes)
        if apply and column_changes:
            for doc_id, old, new in column_changes:
                cur.execute(
                    f"UPDATE {table} SET map_country = %s "
                    f"WHERE doc_id = %s AND map_country = %s",
                    (new, doc_id, old),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"Expected to update exactly 1 row for doc_id={doc_id}, "
                        f"got {cur.rowcount}"
                    )

        # Pass 2: src_doc_raw_metadata->>'Country' JSONB
        cur.execute(
            f"SELECT doc_id, src_doc_raw_metadata->>'Country' "
            f"FROM {table} "
            f"WHERE src_doc_raw_metadata->>'Country' LIKE %s",
            (f"%{OLD_TOKEN}%",),
        )
        rows = cur.fetchall()
        jsonb_changes: List[Tuple[str, str, str]] = []
        for doc_id, val in rows:
            if needs_rewrite(val):
                jsonb_changes.append((doc_id, val, rewrite_country(val)))
        logger.info(
            "[PG] %s.src_doc_raw_metadata->>'Country': %d rows match, %d need rewrite",
            table,
            len(rows),
            len(jsonb_changes),
        )
        for doc_id, old, new in jsonb_changes:
            logger.info("  doc=%s  %r -> %r", doc_id, old, new)
        stats["raw_metadata_rows"] = len(jsonb_changes)
        if apply and jsonb_changes:
            for doc_id, old, new in jsonb_changes:
                # jsonb_set with explicit JSON-encoded string value, scoped by
                # both doc_id and the current value to avoid stomping on
                # anything that changed in the meantime.
                cur.execute(
                    f"UPDATE {table} "
                    f"SET src_doc_raw_metadata = "
                    f"  jsonb_set(src_doc_raw_metadata, '{{Country}}', %s::jsonb) "
                    f"WHERE doc_id = %s "
                    f"AND src_doc_raw_metadata->>'Country' = %s",
                    (json.dumps(new), doc_id, old),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"Expected to update exactly 1 raw_metadata row for "
                        f"doc_id={doc_id}, got {cur.rowcount}"
                    )

    if apply:
        conn.commit()
    return stats


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _scroll_country_points(
    client: QdrantClient, collection: str, batch: int = 200
) -> List[Tuple[str, str]]:
    """Yield (point_id, map_country) for every point with a non-null country."""
    out: List[Tuple[str, str]] = []
    offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=batch,
            with_payload=["map_country"],
            offset=offset,
        )
        for p in points:
            country = p.payload.get("map_country") if p.payload else None
            if country:
                out.append((p.id, country))
        offset = next_offset
        if offset is None:
            break
    return out


def fix_qdrant_collection(client: QdrantClient, collection: str, apply: bool) -> int:
    """Fix map_country in a Qdrant collection. Returns count of points changed."""
    logger.info("[Qdrant] Scanning collection: %s", collection)
    all_pts = _scroll_country_points(client, collection)
    changes: List[Tuple[str, str, str]] = [
        (pid, val, rewrite_country(val)) for pid, val in all_pts if needs_rewrite(val)
    ]
    logger.info(
        "[Qdrant] %s: %d points scanned, %d need rewrite",
        collection,
        len(all_pts),
        len(changes),
    )
    for pid, old, new in changes[:20]:
        logger.info("  point=%s  %r -> %r", pid, old, new)
    if len(changes) > 20:
        logger.info("  …and %d more (omitted)", len(changes) - 20)
    if not apply:
        return len(changes)

    for pid, _old, new in changes:
        for attempt in range(5):
            try:
                client.set_payload(
                    collection_name=collection,
                    payload={"map_country": new},
                    points=[pid],
                    wait=False,
                )
                break
            except Exception as exc:
                wait = 2**attempt
                logger.warning(
                    "Retry %d for %s point %s: %s (sleep %ds)",
                    attempt + 1,
                    collection,
                    pid,
                    exc,
                    wait,
                )
                time.sleep(wait)
        else:
            raise RuntimeError(f"Failed to update {collection} point {pid}")
    return len(changes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _qdrant_client() -> QdrantClient:
    host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    # Auto-resolve Docker hostname to localhost for host execution
    host = host.replace("://qdrant:", "://localhost:")
    return QdrantClient(url=host, api_key=os.getenv("QDRANT_API_KEY"))


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix misspelled country 'Dibouti' -> 'Djibouti' in metadata."
    )
    parser.add_argument(
        "--data-source",
        default="wfp",
        help="Data source name (default: wfp). Affects table and collection names.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the changes. Default is dry-run — nothing is written.",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Skip PostgreSQL updates.",
    )
    parser.add_argument(
        "--skip-qdrant",
        action="store_true",
        help="Skip Qdrant updates.",
    )
    args = parser.parse_args()

    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    load_dotenv(env_path)

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("=" * 60)
    logger.info(" Dibouti → Djibouti country fix  [%s]", mode)
    logger.info(" data_source=%s", args.data_source)
    logger.info("=" * 60)

    pg_stats = {"map_country_rows": 0, "raw_metadata_rows": 0}
    if not args.skip_postgres:
        conn = _postgres_conn()
        try:
            pg_stats = fix_postgres(conn, args.data_source, apply=args.apply)
        finally:
            conn.close()

    qdrant_docs = qdrant_chunks = 0
    if not args.skip_qdrant:
        client = _qdrant_client()
        qdrant_docs = fix_qdrant_collection(
            client, f"documents_{args.data_source}", apply=args.apply
        )
        qdrant_chunks = fix_qdrant_collection(
            client, f"chunks_{args.data_source}", apply=args.apply
        )

    label = "applied" if args.apply else "would change"
    logger.info("-" * 60)
    logger.info(" Summary  [%s]", mode)
    logger.info(
        "   PG  docs.map_country rows %s:           %d",
        label,
        pg_stats["map_country_rows"],
    )
    logger.info(
        "   PG  docs.raw_metadata.Country rows %s:  %d",
        label,
        pg_stats["raw_metadata_rows"],
    )
    logger.info(
        "   Qdrant documents_%s points %s:         %d",
        args.data_source,
        label,
        qdrant_docs,
    )
    logger.info(
        "   Qdrant chunks_%s    points %s:         %d",
        args.data_source,
        label,
        qdrant_chunks,
    )
    if not args.apply:
        logger.info(" Re-run with --apply to actually write the changes.")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
