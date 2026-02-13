"""
Backpopulate map_ fields on documents collection from src_ fields.

During ingestion, the scanner creates both src_ and map_ fields. But older documents
may only have src_ fields. This script adds the missing map_ fields so that /docsearch
endpoint can filter by organization, year, etc.

Usage:
    python scripts/migration/backpopulate_document_map_fields.py
    python scripts/migration/backpopulate_document_map_fields.py --data-source uneg
    python scripts/migration/backpopulate_document_map_fields.py --dry-run
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

# Add project root to path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from pipeline.db import get_db, get_field_mapping  # noqa: E402

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backpopulate_map_fields(data_source="uneg", dry_run=False):
    """
    Backpopulate map_ fields on documents from src_ fields.

    Args:
        data_source: Data source name (e.g., 'uneg', 'worldbank')
        dry_run: If True, only show what would be updated without making changes
    """
    logger.info(f"Starting map_ fields backpopulation for data source: {data_source}")
    logger.info(f"Dry run mode: {dry_run}")

    # Initialize database connection
    db = get_db(data_source)

    # Get field mapping configuration
    field_mapping = get_field_mapping(data_source)
    if not field_mapping:
        logger.warning(f"No field mapping configured for {data_source}")
        return

    logger.info(f"Field mapping: {field_mapping}")

    # Get all documents
    logger.info("Fetching documents from Qdrant...")

    # Scroll all documents
    all_documents = []
    scroll_result = db.client.scroll(
        collection_name=db.documents_collection,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    all_documents.extend(scroll_result[0])
    next_offset = scroll_result[1]

    while next_offset is not None:
        scroll_result = db.client.scroll(
            collection_name=db.documents_collection,
            limit=100,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        all_documents.extend(scroll_result[0])
        next_offset = scroll_result[1]

    total_docs = len(all_documents)
    logger.info(f"Found {total_docs} documents")

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for idx, point in enumerate(all_documents, 1):
        if idx % 10 == 0 or idx == 1:
            logger.info(f"Processing document {idx}/{total_docs}: {point.id}")

        payload = point.payload
        if not payload:
            skipped_count += 1
            continue

        # Build updates dict with map_ fields from src_ fields
        updates = {}

        # For each core field in the mapping, check if we need to add map_ field
        for core_field, source_field in field_mapping.items():
            map_field = f"map_{core_field}"
            src_field = f"src_{source_field}"

            # Skip if map_ field already exists
            if map_field in payload:
                continue

            # If src_ field exists, copy it to map_ field
            if src_field in payload:
                updates[map_field] = payload[src_field]
                logger.debug(
                    f"  Mapping {src_field} -> {map_field}: {payload[src_field]}"
                )

        if not updates:
            skipped_count += 1
            continue

        # Apply updates to Qdrant document using set_payload directly
        try:
            if dry_run:
                logger.info(f"  [DRY RUN] Would update {point.id} with: {updates}")
            else:
                db.client.set_payload(
                    collection_name=db.documents_collection,
                    payload=updates,
                    points=[point.id],
                    wait=True,
                )
                logger.info(f"  ✓ Updated {point.id} with {len(updates)} map_ fields")

            updated_count += 1

        except Exception as e:
            logger.error(f"  ✗ Failed to update {point.id}: {e}")
            error_count += 1

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Map Fields Backpopulation Summary:")
    logger.info(f"  Total documents:     {total_docs}")
    logger.info(f"  Documents updated:   {updated_count}")
    logger.info(f"  Documents skipped:   {skipped_count}")
    logger.info(f"  Errors:              {error_count}")
    logger.info("=" * 60)

    if dry_run:
        logger.info("\nThis was a dry run. No changes were made.")
        logger.info("Run without --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Backpopulate map_ fields on documents from src_ fields."
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

    backpopulate_map_fields(data_source=args.data_source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
