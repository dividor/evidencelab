#!/usr/bin/env python3
"""
Wipe existing taxonomy data from sys_taxonomies column.

This script clears all taxonomy data from the sys_taxonomies column
to prepare for migration to the new structure that includes LLM reasons.

Usage:
    source .env
    python scripts/maintenance/wipe_taxonomy_data.py --data-source uneg
"""

import argparse
import logging
import os
import sys

# Add repo root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def wipe_taxonomy_data(data_source: str):
    """Wipe sys_taxonomies column from all documents."""
    logger.info(f"Wiping taxonomy data for data source: {data_source}")

    db = get_db(data_source)

    # Get the table name
    docs_table = db.pg.docs_table
    chunks_table = db.pg.chunks_table

    logger.info(f"Clearing sys_taxonomies from table: {docs_table}")

    # Wipe sys_taxonomies from documents table
    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {docs_table} SET sys_taxonomies = NULL")
            docs_affected = cur.rowcount
        conn.commit()

    logger.info(f"✓ Wiped sys_taxonomies from {docs_affected} documents")

    # Try to wipe from chunks table (might not have this column)
    try:
        logger.info(f"Clearing sys_taxonomies from chunks table: {chunks_table}")
        with db.pg._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE {chunks_table} SET sys_taxonomies = NULL")
                chunks_affected = cur.rowcount
            conn.commit()
        logger.info(f"✓ Wiped sys_taxonomies from {chunks_affected} chunks")
    except Exception as e:
        logger.warning(f"Could not wipe chunks (column may not exist): {e}")

    logger.info("✓ Taxonomy data wipe complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Wipe existing taxonomy data from database"
    )
    parser.add_argument(
        "--data-source", required=True, help="Data source name (e.g., uneg, worldbank)"
    )

    args = parser.parse_args()

    wipe_taxonomy_data(args.data_source)
