#!/usr/bin/env python3
"""
Fix concatenated country values in Qdrant and PostgreSQL.

The UNEG scraper's BeautifulSoup get_text(strip=True) concatenated
multi-country values without a separator, producing entries like
"NepalIndia" instead of "Nepal; India".

This script:
  1. Identifies concatenated country values using regex boundary detection
  2. Splits them using 3-pass regex (lowercase→uppercase, period→uppercase, PDR→uppercase)
  3. Updates Qdrant chunks/docs and PostgreSQL docs/chunks

Usage:
    python scripts/fixes/fix_country_concatenation.py \\
        --data-source uneg --dry-run
    python scripts/fixes/fix_country_concatenation.py \\
        --data-source uneg

Connection settings are read from .env (QDRANT_HOST, POSTGRES_HOST, etc.)
with sensible localhost defaults. Inside Docker, POSTGRES_HOST is
automatically resolved to 'postgres'.
"""

import argparse
import logging
import os
import re
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def split_countries(concatenated: str) -> str:
    """Split a concatenated country string into '; '-separated countries.

    Uses 3-pass regex boundary detection:
      1. lowercase→uppercase: 'FranceGermany' → 'France; Germany'
      2. period→uppercase:    'Rep.Chad'      → 'Rep.; Chad'
      3. PDR→uppercase:       'PDRMyanmar'    → 'PDR; Myanmar'

    Values already containing '; ' are returned as-is.
    """
    if not concatenated or "; " in concatenated:
        return concatenated

    result = re.sub(r"([a-z])([A-Z])", r"\1; \2", concatenated)
    result = re.sub(r"(\.)([A-Z][a-z])", r"\1; \2", result)
    result = re.sub(r"(PDR)([A-Z])", r"\1; \2", result)
    return result


def needs_splitting(value: str) -> bool:
    """Check if a country value is a concatenated multi-country string."""
    return value != split_countries(value)


def fix_qdrant_collection(client, collection_name, dry_run):
    """Fix map_country in a Qdrant collection."""
    logger.info("Scanning Qdrant collection: %s", collection_name)

    # Collect all points with their country values
    fixes = {}  # point_id -> new_value
    offset = None
    scanned = 0
    while True:
        results = client.scroll(
            collection_name,
            limit=500,
            with_payload=["map_country"],
            offset=offset,
        )
        points, next_offset = results
        for point in points:
            country = point.payload.get("map_country", "")
            if country and needs_splitting(country):
                fixes[point.id] = split_countries(country)
        scanned += len(points)
        if scanned % 10000 == 0:
            logger.info("  Scanned %d points, %d need fixing...", scanned, len(fixes))
        offset = next_offset
        if offset is None:
            break

    logger.info(
        "Collection %s: %d/%d points need fixing",
        collection_name,
        len(fixes),
        scanned,
    )

    if dry_run:
        for pid, new_val in list(fixes.items())[:10]:
            logger.info("  [DRY RUN] %s -> %s", pid, new_val)
        return len(fixes)

    # Apply fixes in batches
    point_ids = list(fixes.keys())
    batch_size = 50
    for i in range(0, len(point_ids), batch_size):
        batch = point_ids[i : i + batch_size]
        for pid in batch:
            for attempt in range(5):
                try:
                    client.set_payload(
                        collection_name,
                        payload={"map_country": fixes[pid]},
                        points=[pid],
                        wait=False,
                    )
                    break
                except Exception as e:
                    wait_time = 2**attempt
                    logger.warning(
                        "Retry %d for point %s: %s (wait %ds)",
                        attempt + 1,
                        pid,
                        e,
                        wait_time,
                    )
                    time.sleep(wait_time)
        done = min(i + batch_size, len(point_ids))
        if done % 500 == 0 or done == len(point_ids):
            logger.info("  Updated %d/%d points", done, len(point_ids))
        time.sleep(0.1)

    return len(fixes)


def fix_postgres_table(conn, table_name, dry_run):
    """Fix map_country in a PostgreSQL table."""
    logger.info("Scanning PostgreSQL table: %s", table_name)

    cursor = conn.cursor()

    # Check if column exists before querying
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = 'map_country'",
        (table_name,),
    )
    if not cursor.fetchone():
        logger.info("Table %s has no map_country column, skipping", table_name)
        return 0

    # Find all distinct concatenated country values
    cursor.execute(
        f"SELECT DISTINCT map_country FROM {table_name} "
        f"WHERE map_country IS NOT NULL AND map_country != ''"
    )
    all_values = [row[0] for row in cursor.fetchall()]

    mapping = {}
    for val in all_values:
        if needs_splitting(val):
            mapping[val] = split_countries(val)

    logger.info(
        "Table %s: %d/%d distinct values need fixing",
        table_name,
        len(mapping),
        len(all_values),
    )

    if dry_run:
        for old, new in list(mapping.items())[:10]:
            logger.info("  [DRY RUN] %r -> %r", old, new)
        return len(mapping)

    # Apply fixes
    for old_val, new_val in mapping.items():
        cursor.execute(
            f"UPDATE {table_name} SET map_country = %s " f"WHERE map_country = %s",
            (new_val, old_val),
        )
        logger.info(
            "  Updated %d rows: %r -> %r",
            cursor.rowcount,
            old_val[:60],
            new_val[:60],
        )

    conn.commit()
    return len(mapping)


def main():
    parser = argparse.ArgumentParser(
        description="Fix concatenated country values in Qdrant and PostgreSQL"
    )
    parser.add_argument(
        "--data-source",
        default="uneg",
        help="Data source name (default: uneg)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )
    parser.add_argument(
        "--collection",
        choices=["chunks", "docs", "all"],
        default="all",
        help="Which collection(s) to fix (default: all)",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Skip PostgreSQL (useful when psycopg2 not available)",
    )
    args = parser.parse_args()

    # Load .env from repo root
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    load_dotenv(env_path)

    ds = args.data_source
    qdrant_host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    # Auto-convert Docker hostname to localhost for host execution
    qdrant_host = qdrant_host.replace("://qdrant:", "://localhost:")
    client = QdrantClient(url=qdrant_host, api_key=qdrant_api_key)

    # Qdrant
    chunks_collection = f"chunks_{ds}"
    docs_collection = f"documents_{ds}"

    if args.collection in ("chunks", "all"):
        fix_qdrant_collection(client, chunks_collection, args.dry_run)
    if args.collection in ("docs", "all"):
        fix_qdrant_collection(client, docs_collection, args.dry_run)

    # PostgreSQL
    if not args.skip_postgres:
        try:
            import psycopg2

            from pipeline.db.postgres_client_base import build_postgres_dsn

            dsn = build_postgres_dsn()
            conn = psycopg2.connect(dsn)
            docs_table = f"docs_{ds}"
            chunks_table = f"chunks_{ds}"
            if args.collection in ("docs", "all"):
                fix_postgres_table(conn, docs_table, args.dry_run)
            if args.collection in ("chunks", "all"):
                fix_postgres_table(conn, chunks_table, args.dry_run)
            conn.close()
        except ImportError:
            logger.info("psycopg2 not available, skipping PostgreSQL")

    logger.info("Done!")


if __name__ == "__main__":
    main()
