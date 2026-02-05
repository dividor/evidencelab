#!/usr/bin/env python3
"""
Fix Qdrant database by removing duplicate records.
Keeps the "best" record for each unique filepath (most processed status).
"""
import argparse
from collections import defaultdict

from pipeline.db import get_default_db

# Status priority - higher is better (keep the most processed version)
STATUS_PRIORITY = {
    "indexed": 100,
    "summarized": 90,
    "parsed": 80,
    "downloaded": 70,
    "parsing": 60,
    "summarizing": 50,
    "parse_failed": 40,
    "summarize_failed": 30,
    "download_error": 20,
    "download_failed": 10,
    "unknown": 0,
}


def get_status_priority(status):
    """Get priority for a status (higher = better)"""
    return STATUS_PRIORITY.get(status, 0)


def main(confirm=False):
    db = get_default_db()

    print("\n" + "=" * 80)
    print("FIXING QDRANT DUPLICATE RECORDS")
    print("=" * 80)

    # Get all documents WITH IDs
    print("\n📥 Loading all documents from database...")
    docs_with_ids = list(db.get_all_documents_with_ids())
    print(f"   Loaded {len(docs_with_ids):,} records")

    # Group by filepath
    print("\n🔍 Grouping records by filepath...")
    filepath_groups = defaultdict(list)

    for doc_id, doc in docs_with_ids:
        filepath = doc.get("filepath", "")
        if filepath:
            # Store the document with its ID
            filepath_groups[filepath].append((doc_id, doc))

    # Find duplicates
    duplicates = {fp: group for fp, group in filepath_groups.items() if len(group) > 1}

    print(f"   Unique filepaths: {len(filepath_groups):,}")
    print(f"   Duplicate filepaths: {len(duplicates):,}")

    if not duplicates:
        print("\n✅ No duplicates found! Database is clean.")
        return

    # Calculate how many records will be deleted
    total_dupes = sum(len(group) - 1 for group in duplicates.values())
    print(f"   Records to delete: {total_dupes:,}")

    # Show examples
    print("\n📄 Example duplicates (top 5):")
    print("-" * 80)
    for fp, group in sorted(duplicates.items(), key=lambda x: -len(x[1]))[:5]:
        print(f"\n   {fp[:70]}...")
        print(f"   Has {len(group)} records:")
        for doc_id, doc in group:
            status = doc.get("status", "unknown")
            title = doc.get("title", "Unknown")[:40]
            print(f"      - ID: {doc_id[:12]}... Status: {status:15} Title: {title}...")

    # Ask for confirmation
    print("\n" + "=" * 80)
    print("⚠️  READY TO DELETE DUPLICATES")
    print("=" * 80)
    print(f"\nThis will delete {total_dupes:,} duplicate records from Qdrant.")
    print(f"Final database will have {len(docs_with_ids) - total_dupes:,} records.")
    print(
        "\nFor each filepath, the record with the highest status priority will be kept:"
    )
    print("  Priority: indexed > summarized > parsed > downloaded > errors")

    if not confirm:
        print("\n⚠️  DRY RUN - Use --confirm to actually delete duplicates")
        print("❌ Aborted. No changes made.")
        return

    print("\n✅ --confirm flag provided, proceeding with deletion...")

    # Delete duplicates
    print("\n🗑️  Deleting duplicate records...")
    deleted_count = 0
    kept_count = 0

    for filepath, group in duplicates.items():
        # Sort by priority (highest first)
        sorted_group = sorted(
            group,
            key=lambda item: (
                get_status_priority(item[1].get("status", "unknown")),
                item[0],  # Tie-breaker: use ID
            ),
            reverse=True,
        )

        # Keep the first (highest priority), delete the rest
        keep_id, keep_doc = sorted_group[0]
        to_delete = sorted_group[1:]

        kept_count += 1

        # Delete duplicates from Qdrant
        for doc_id, doc in to_delete:
            try:
                db.client.delete(
                    collection_name=db.documents_collection, points_selector=[doc_id]
                )
                deleted_count += 1

                if deleted_count % 100 == 0:
                    print(f"   Deleted {deleted_count:,}/{total_dupes:,}...")

            except Exception as e:
                print(f"   ⚠️  Error deleting {doc_id}: {e}")

    print(f"\n✅ Deleted {deleted_count:,} duplicate records")
    print(f"✅ Kept {kept_count:,} best records")

    # Verify
    print("\n🔍 Verifying...")
    final_docs = list(db.get_all_documents())
    final_unique = len(set(d.get("filepath") for d in final_docs if d.get("filepath")))

    print(f"   Final database records: {len(final_docs):,}")
    print(f"   Final unique filepaths: {final_unique:,}")

    if len(final_docs) == final_unique:
        print("\n✅ SUCCESS! Database is now clean - no duplicates!")
    else:
        print(
            f"\n⚠️  Warning: Still have {len(final_docs) - final_unique} potential duplicates"
        )

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix Qdrant database by removing duplicate records"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete duplicates (without this, it's a dry run)",
    )
    args = parser.parse_args()

    main(confirm=args.confirm)
