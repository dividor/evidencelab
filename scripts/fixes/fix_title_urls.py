#!/usr/bin/env python3
"""
Fix titles with URLs appended in both JSON files and Qdrant.

This script:
1. Scans all JSON metadata files and removes URLs from titles
2. Updates Qdrant documents and chunks with cleaned titles
"""

import json
import logging
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Regex to match URL suffix in titles
# Matches: " - https://..." or " - http://..." at the end
URL_SUFFIX_PATTERN = re.compile(r"\s*-\s*https?://[^\s]+$")


def clean_title(title: str) -> str:
    """Remove URL suffix from title."""
    if not title:
        return title
    return URL_SUFFIX_PATTERN.sub("", title).strip()


def fix_json_files(base_dir: str = "./data/pdfs", dry_run: bool = False) -> dict:
    """
    Fix all JSON metadata files in the data directory.

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

    for json_path in json_files:
        stats["checked"] += 1

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            title = data.get("title", "")
            if not title or "http" not in title:
                continue

            cleaned_title = clean_title(title)
            if cleaned_title != title:
                if dry_run:
                    logger.info(f"Would fix: {json_path.name}")
                    logger.info(f"  Before: {title[:80]}...")
                    logger.info(f"  After:  {cleaned_title[:80]}...")
                else:
                    data["title"] = cleaned_title
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Fixed: {json_path.name}")

                stats["fixed"] += 1

        except Exception as e:
            logger.error(f"Error processing {json_path}: {e}")
            stats["errors"] += 1

    return stats


def fix_qdrant(dry_run: bool = False) -> dict:
    """
    Fix titles in Qdrant documents and chunks collections.

    Returns:
        Dict with statistics
    """

    from pipeline.db import get_default_db

    db = get_default_db()

    stats = {"docs_checked": 0, "docs_fixed": 0, "chunks_fixed": 0, "errors": 0}

    logger.info("\nFixing Qdrant documents collection...")

    # Fix documents collection
    docs_to_fix = []
    for doc_id, doc in db.get_all_documents_with_ids():
        stats["docs_checked"] += 1
        title = doc.get("title", "")

        if title and "http" in title:
            cleaned_title = clean_title(title)
            if cleaned_title != title:
                docs_to_fix.append((doc_id, cleaned_title))

    logger.info(f"Found {len(docs_to_fix)} documents with URLs in titles")

    if not dry_run:
        for doc_id, cleaned_title in docs_to_fix:
            try:
                db.update_document(doc_id, {"title": cleaned_title})
                stats["docs_fixed"] += 1
                if stats["docs_fixed"] % 100 == 0:
                    logger.info(f"  Fixed {stats['docs_fixed']} documents...")
            except Exception as e:
                logger.error(f"Error updating document {doc_id}: {e}")
                stats["errors"] += 1
    else:
        stats["docs_fixed"] = len(docs_to_fix)

    # Fix chunks collection
    logger.info("\nFixing Qdrant chunks collection...")

    try:
        # Scroll through all chunks
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
                title = point.payload.get("title", "")
                if title and "http" in title:
                    cleaned_title = clean_title(title)
                    if cleaned_title != title:
                        chunks_batch.append((str(point.id), cleaned_title))

            if offset is None:
                break

        logger.info(f"Found {len(chunks_batch)} chunks with URLs in titles")

        if not dry_run:
            for chunk_id, cleaned_title in chunks_batch:
                try:
                    db.client.set_payload(
                        collection_name="chunks",
                        payload={"title": cleaned_title},
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
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix titles with URLs in JSON files and Qdrant"
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
    parser.add_argument(
        "--base-dir", default="./data/pdfs", help="Base directory for JSON files"
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN - No changes will be made")
        logger.info("=" * 60)

    total_stats = {}

    # Fix JSON files
    if not args.qdrant_only:
        logger.info("\n" + "=" * 60)
        logger.info("FIXING JSON FILES")
        logger.info("=" * 60)
        json_stats = fix_json_files(args.base_dir, dry_run=args.dry_run)
        total_stats["json"] = json_stats
        logger.info(
            f"\nJSON files: checked={json_stats['checked']}, fixed={json_stats['fixed']}, errors={json_stats['errors']}"  # noqa: E501
        )

    # Fix Qdrant
    if not args.json_only:
        logger.info("\n" + "=" * 60)
        logger.info("FIXING QDRANT")
        logger.info("=" * 60)
        qdrant_stats = fix_qdrant(dry_run=args.dry_run)
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
