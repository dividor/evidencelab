#!/usr/bin/env python3
"""
Fix file paths in JSON metadata files and Qdrant after moving data to a new location.

Usage:
    python scripts/fix_data_paths.py --old-prefix "./data/pdfs" --new-prefix "./data/uneg/pdfs"
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def fix_json_files(
    base_dir: str, old_prefix: str, new_prefix: str, dry_run: bool = False
) -> dict:
    """
    Fix filepath fields in all JSON metadata files.

    Args:
        base_dir: Directory containing JSON files to fix
        old_prefix: Old path prefix to replace (e.g., "./data/pdfs")
        new_prefix: New path prefix (e.g., "./data/uneg/pdfs")
        dry_run: If True, don't actually modify files

    Returns:
        Dict with statistics
    """
    stats = {"checked": 0, "fixed": 0, "errors": 0}
    base_path = Path(base_dir)

    if not base_path.exists():
        logger.error(f"Directory not found: {base_dir}")
        return stats

    json_files = list(base_path.rglob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files to check")

    # Fields that contain file paths
    path_fields = ["filepath", "parsed_folder", "error_file"]

    for json_path in json_files:
        stats["checked"] += 1

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            modified = False
            for field in path_fields:
                if field in data and data[field] and old_prefix in str(data[field]):
                    old_value = data[field]
                    new_value = old_value.replace(old_prefix, new_prefix)
                    data[field] = new_value
                    modified = True
                    if dry_run:
                        logger.info(f"Would fix {field} in {json_path.name}:")
                        logger.info(f"  {old_value} -> {new_value}")

            if modified:
                if not dry_run:
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                stats["fixed"] += 1

        except Exception as e:
            logger.error(f"Error processing {json_path}: {e}")
            stats["errors"] += 1

    return stats


def fix_qdrant(old_prefix: str, new_prefix: str, dry_run: bool = False) -> dict:
    """
    Fix filepath fields in Qdrant documents and chunks.

    Args:
        old_prefix: Old path prefix to replace
        new_prefix: New path prefix
        dry_run: If True, don't actually modify Qdrant

    Returns:
        Dict with statistics
    """
    # Import here to avoid issues when running outside Docker
    from pipeline.db import get_default_db

    db = get_default_db()

    stats = {"docs_checked": 0, "docs_fixed": 0, "chunks_fixed": 0, "errors": 0}

    # Fields that contain file paths
    path_fields = ["filepath", "parsed_folder", "error_file"]

    logger.info("\nFixing Qdrant documents collection...")

    # Fix documents collection
    docs_to_fix = []
    for doc_id, doc in db.get_all_documents_with_ids():
        stats["docs_checked"] += 1

        updates = {}
        for field in path_fields:
            if field in doc and doc[field] and old_prefix in str(doc[field]):
                old_value = doc[field]
                new_value = old_value.replace(old_prefix, new_prefix)
                updates[field] = new_value

        if updates:
            docs_to_fix.append((doc_id, updates))

    logger.info(f"Found {len(docs_to_fix)} documents with paths to fix")

    if not dry_run:
        for doc_id, updates in docs_to_fix:
            try:
                db.update_document(doc_id, updates)
                stats["docs_fixed"] += 1
                if stats["docs_fixed"] % 500 == 0:
                    logger.info(f"  Fixed {stats['docs_fixed']} documents...")
            except Exception as e:
                logger.error(f"Error updating document {doc_id}: {e}")
                stats["errors"] += 1
    else:
        stats["docs_fixed"] = len(docs_to_fix)
        if docs_to_fix:
            logger.info(f"Sample fix: {docs_to_fix[0]}")

    # Fix chunks collection
    logger.info("\nFixing Qdrant chunks collection...")

    try:
        offset = None
        chunks_batch = []

        while True:
            results, offset = db.client.scroll(
                collection_name="chunks",
                limit=100,
                offset=offset,
                with_payload=True,
            )

            for point in results:
                updates = {}
                for field in path_fields:
                    value = point.payload.get(field)
                    if value and old_prefix in str(value):
                        updates[field] = value.replace(old_prefix, new_prefix)

                if updates:
                    chunks_batch.append((str(point.id), updates))

            if offset is None:
                break

        logger.info(f"Found {len(chunks_batch)} chunks with paths to fix")

        if not dry_run:
            for chunk_id, updates in chunks_batch:
                try:
                    db.client.set_payload(
                        collection_name="chunks",
                        payload=updates,
                        points=[chunk_id],
                    )
                    stats["chunks_fixed"] += 1
                    if stats["chunks_fixed"] % 500 == 0:
                        logger.info(f"  Fixed {stats['chunks_fixed']} chunks...")
                except Exception as e:
                    logger.error(f"Error updating chunk {chunk_id}: {e}")
                    stats["errors"] += 1
        else:
            stats["chunks_fixed"] = len(chunks_batch)

    except Exception as e:
        logger.error(f"Error processing chunks: {e}")
        stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Fix file paths in JSON files and Qdrant"
    )
    parser.add_argument(
        "--old-prefix", required=True, help="Old path prefix to replace"
    )
    parser.add_argument("--new-prefix", required=True, help="New path prefix")
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Base directory for JSON files (defaults to new-prefix)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument(
        "--json-only", action="store_true", help="Only fix JSON files, not Qdrant"
    )
    parser.add_argument(
        "--qdrant-only", action="store_true", help="Only fix Qdrant, not JSON files"
    )

    args = parser.parse_args()

    # Default base_dir to new_prefix
    base_dir = args.base_dir if args.base_dir else args.new_prefix

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN - No changes will be made")
        logger.info("=" * 60)

    logger.info(f"Old prefix: {args.old_prefix}")
    logger.info(f"New prefix: {args.new_prefix}")

    total_stats = {}

    # Fix JSON files
    if not args.qdrant_only:
        logger.info("\n" + "=" * 60)
        logger.info("FIXING JSON FILES")
        logger.info("=" * 60)
        json_stats = fix_json_files(
            base_dir, args.old_prefix, args.new_prefix, dry_run=args.dry_run
        )
        total_stats["json"] = json_stats
        logger.info(
            f"\nJSON: checked={json_stats['checked']}, fixed={json_stats['fixed']}, errors={json_stats['errors']}"  # noqa: E501
        )

    # Fix Qdrant
    if not args.json_only:
        logger.info("\n" + "=" * 60)
        logger.info("FIXING QDRANT")
        logger.info("=" * 60)
        qdrant_stats = fix_qdrant(
            args.old_prefix, args.new_prefix, dry_run=args.dry_run
        )
        total_stats["qdrant"] = qdrant_stats
        logger.info(
            f"\nQdrant: docs_checked={qdrant_stats['docs_checked']}, docs_fixed={qdrant_stats['docs_fixed']}, chunks_fixed={qdrant_stats['chunks_fixed']}, errors={qdrant_stats['errors']}"  # noqa: E501
        )

    logger.info("\n" + "=" * 60)
    logger.info("COMPLETE")
    logger.info("=" * 60)

    return 0 if all(s.get("errors", 0) == 0 for s in total_stats.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
