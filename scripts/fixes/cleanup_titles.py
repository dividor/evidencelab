#!/usr/bin/env python3
"""
Script to clean up document titles in Qdrant that have URLs appended.

Example bad title:
  "Mid-Term Evaluation Report on X project - https://example.com/doc/123"

Will be cleaned to:
  "Mid-Term Evaluation Report on X project"
"""

import re
import sys
from pathlib import Path

from pipeline.db import get_default_db

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


db = get_default_db()


def clean_title(title: str) -> str:
    """Remove URL suffix from title if present."""
    if not title:
        return title

    # Pattern: " - http://" or " - https://" followed by anything to end of string
    pattern = r"\s+-\s+https?://[^\s]+$"
    cleaned = re.sub(pattern, "", title)
    return cleaned


def main():
    print("=" * 60)
    print("Title Cleanup Script")
    print("=" * 60)

    # Get all documents with their IDs
    print("\nFetching all documents...")
    docs_with_ids = list(db.get_all_documents_with_ids())
    print(f"Found {len(docs_with_ids)} documents")

    # Find documents with URL in title
    docs_to_fix = []
    for doc_id, doc in docs_with_ids:
        title = doc.get("title", "")
        cleaned = clean_title(title)
        if cleaned != title:
            docs_to_fix.append({"id": doc_id, "old_title": title, "new_title": cleaned})

    print(f"\nFound {len(docs_to_fix)} documents with URLs in title")

    if not docs_to_fix:
        print("No documents need cleaning. Exiting.")
        return

    # Show examples
    print("\nExamples of titles to fix:")
    for doc in docs_to_fix[:5]:
        print(f"\n  OLD: {doc['old_title'][:80]}...")
        print(f"  NEW: {doc['new_title'][:80]}...")

    # Ask for confirmation
    if "--yes" not in sys.argv:
        response = input(f"\nProceed to update {len(docs_to_fix)} documents? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return

    # Update documents in Qdrant
    print("\nUpdating documents...")
    updated = 0
    failed = 0

    for doc in docs_to_fix:
        try:
            # Update the document payload
            db.client.set_payload(
                collection_name="documents",
                payload={"title": doc["new_title"]},
                points=[doc["id"]],
            )
            updated += 1

            if updated % 10 == 0:
                print(f"  Updated {updated}/{len(docs_to_fix)}...")
        except Exception as e:
            print(f"  Failed to update {doc['id']}: {e}")
            failed += 1

    print(f"\nDone! Updated {updated} documents, {failed} failed.")

    # Also update chunks if they have title field
    print("\nChecking chunks for title field...")
    try:
        # Sample a chunk to see if it has title field
        chunks = db.client.scroll(collection_name="chunks", limit=1, with_payload=True)

        if chunks[0] and "title" in chunks[0][0].payload:
            print("Chunks have title field. Updating chunks...")

            # Get all chunks with bad titles
            chunk_count = 0
            offset = None

            while True:
                batch, offset = db.client.scroll(
                    collection_name="chunks",
                    limit=100,
                    offset=offset,
                    with_payload=["title"],
                )

                if not batch:
                    break

                for chunk in batch:
                    title = chunk.payload.get("title", "")
                    cleaned = clean_title(title)
                    if cleaned != title:
                        try:
                            db.client.set_payload(
                                collection_name="chunks",
                                payload={"title": cleaned},
                                points=[chunk.id],
                            )
                            chunk_count += 1
                        except Exception as e:
                            print(f"  Failed to update chunk {chunk.id}: {e}")

                if offset is None:
                    break

            print(f"Updated {chunk_count} chunks.")
        else:
            print("Chunks don't have title field. Skipping.")
    except Exception as e:
        print(f"Error checking/updating chunks: {e}")

    print("\n" + "=" * 60)
    print("Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
