"""
Backpopulate taxonomy fields on documents collection from Postgres.

This script:
1. Reads taxonomy data from Postgres taxonomies table for all documents
2. Updates each document in Qdrant documents collection with taxonomy fields
3. Ensures documents can be filtered by taxonomy (e.g., tag_sdg, tag_cross_cutting_theme)

Usage:
    python scripts/migration/backpopulate_document_taxonomies.py
    python scripts/migration/backpopulate_document_taxonomies.py --data-source uneg
    python scripts/migration/backpopulate_document_taxonomies.py --dry-run
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from pipeline.db import get_db
from pipeline.db.postgres_client import PostgresClient

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backpopulate_taxonomies(data_source="uneg", dry_run=False):
    """
    Backpopulate taxonomy fields on documents from Postgres.

    Args:
        data_source: Data source name (e.g., 'uneg', 'worldbank')
        dry_run: If True, only show what would be updated without making changes
    """
    logger.info(f"Starting taxonomy backpopulation for data source: {data_source}")
    logger.info(f"Dry run mode: {dry_run}")

    # Initialize database connections
    db = get_db(data_source)
    pg = PostgresClient(data_source)

    # Get all taxonomy configurations - use the database's method
    pipeline_cfg = db._load_pipeline_config()
    taxonomies = pipeline_cfg.get("tag", {}).get("taxonomies", {})

    if not taxonomies:
        logger.warning(f"No taxonomies configured for {data_source}")
        return

    logger.info(f"Found {len(taxonomies)} taxonomy types: {list(taxonomies.keys())}")

    # Get all documents with taxonomy data from Postgres
    logger.info("Fetching documents from Postgres...")

    # Query to get all doc_ids with their taxonomies
    docs_query = f"""
        SELECT doc_id, sys_taxonomies
        FROM docs_{data_source}
        WHERE sys_taxonomies IS NOT NULL
        ORDER BY doc_id
    """

    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(docs_query)
            rows = cur.fetchall()

    total_docs = len(rows)

    if total_docs == 0:
        logger.warning("No documents found with sys_taxonomies data")
        return

    logger.info(f"Found {total_docs} documents with taxonomy data")

    updated_count = 0
    error_count = 0
    skipped_count = 0

    for idx, (doc_id, sys_taxonomies) in enumerate(rows, 1):
        if idx % 100 == 0 or idx == 1:
            logger.info(f"Processing document {idx}/{total_docs}: {doc_id}")

        if not sys_taxonomies:
            skipped_count += 1
            continue

        # Build updates dict with taxonomy fields
        updates = {}

        # Extract taxonomy codes from the JSON structure
        # Structure: {"sdg": [{"code": "sdg1", ...}], "cross_cutting_theme": [{"code": "gender_equality", ...}]}
        for tax_type, tax_list in sys_taxonomies.items():
            if not isinstance(tax_list, list):
                continue

            # Extract codes from list
            codes = [
                item.get("code")
                for item in tax_list
                if isinstance(item, dict) and "code" in item
            ]

            if codes:
                field_name = f"tag_{tax_type}"
                # Store as array for Qdrant MatchAny support
                updates[field_name] = codes

        if not updates:
            skipped_count += 1
            continue

        # Apply updates to Qdrant document using set_payload directly
        try:
            if dry_run:
                logger.debug(f"  [DRY RUN] Would update {doc_id} with: {updates}")
            else:
                # Convert string doc_id to int if needed
                qdrant_doc_id = doc_id
                if isinstance(doc_id, str):
                    try:
                        qdrant_doc_id = int(doc_id)
                    except ValueError:
                        pass  # Keep as string if not convertible

                db.client.set_payload(
                    collection_name=db.documents_collection,
                    payload=updates,
                    points=[qdrant_doc_id],
                    wait=True,
                )
                logger.debug(
                    f"  ✓ Updated {doc_id} with {len(updates)} taxonomy fields"
                )

            updated_count += 1

        except Exception as e:
            logger.error(f"  ✗ Failed to update {doc_id}: {e}")
            error_count += 1

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Taxonomy Backpopulation Summary:")
    logger.info(f"  Total documents with taxonomies: {total_docs}")
    logger.info(f"  Documents updated:               {updated_count}")
    logger.info(f"  Documents skipped:               {skipped_count}")
    logger.info(f"  Errors:                          {error_count}")
    logger.info("=" * 60)

    if dry_run:
        logger.info("\nThis was a dry run. No changes were made.")
        logger.info("Run without --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Backpopulate taxonomy fields on documents from Postgres."
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="uneg",
        help="Data source name (default: uneg)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    args = parser.parse_args()

    backpopulate_taxonomies(data_source=args.data_source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
