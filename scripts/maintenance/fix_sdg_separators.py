#!/usr/bin/env python3
"""
Fix SDG separator issue in existing records.

The sdgs field in src_doc_raw_metadata has values concatenated without separators:
"SDG1 - No PovertySDG10 - Reduced Inequalities..."

This script adds "; " separator between SDG values:
"SDG1 - No Poverty; SDG10 - Reduced Inequalities; ..."

Usage:
    docker exec pipeline python scripts/maintenance/fix_sdg_separators.py --data-source uneg
"""

import argparse
import logging
import os
import re
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


def fix_sdg_separators(data_source: str, dry_run: bool = False):
    """Fix SDG separators in all documents."""
    logger.info(f"Fixing SDG separators for data source: {data_source}")
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    db = get_db(data_source)
    docs_table = db.pg.docs_table

    # Fetch all documents with sdgs field in metadata that need fixing
    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT doc_id, src_doc_raw_metadata->>'sdgs' as sdgs
                FROM {docs_table}
                WHERE src_doc_raw_metadata->>'sdgs' IS NOT NULL
                  AND src_doc_raw_metadata->>'sdgs' != ''
                  AND src_doc_raw_metadata->>'sdgs' NOT LIKE '%; %'
            """
            )
            rows = cur.fetchall()

    logger.info(f"Found {len(rows)} documents with SDG data needing fixes")

    if not rows:
        logger.info("No documents need fixing")
        return

    # Show some examples
    logger.info("\nExamples of data to be fixed:")
    for i, (doc_id, sdgs) in enumerate(rows[:3]):
        # Add separators: insert "; " before each "SDG" except the first
        fixed_sdg = re.sub(r"(SDG\d+[^S]*?)(?=SDG)", r"\1; ", sdgs)
        logger.info(f"  Doc {doc_id}:")
        logger.info(f"    Before: {sdgs[:100]}...")
        logger.info(f"    After:  {fixed_sdg[:100]}...")

    if dry_run:
        logger.info(f"\nDRY RUN: Would fix {len(rows)} documents")
        return

    # Update records
    logger.info(f"\nUpdating {len(rows)} documents...")
    updated = 0

    with db.pg._get_conn() as conn:
        with conn.cursor() as cur:
            for doc_id, sdgs in rows:
                # Add separators: insert "; " before each "SDG" except the first
                # Pattern matches "SDG" + digits + content, lookahead for next "SDG"
                fixed_sdg = re.sub(r"(SDG\d+[^S]*?)(?=SDG)", r"\1; ", sdgs)

                # Update the sdgs field in the JSONB column
                cur.execute(
                    f"""
                    UPDATE {docs_table}
                    SET src_doc_raw_metadata = jsonb_set(
                        src_doc_raw_metadata,
                        '{{sdgs}}',
                        to_jsonb(%s::text)
                    )
                    WHERE doc_id = %s
                    """,
                    (fixed_sdg, doc_id),
                )
                updated += 1

                if updated % 1000 == 0:
                    logger.info(f"  Updated {updated}/{len(rows)} documents...")

        conn.commit()

    logger.info(f"✓ Successfully updated {updated} documents")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix SDG separator issue in existing records"
    )
    parser.add_argument(
        "--data-source", required=True, help="Data source name (e.g., uneg, worldbank)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )

    args = parser.parse_args()

    fix_sdg_separators(args.data_source, dry_run=args.dry_run)
