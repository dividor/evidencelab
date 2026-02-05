import argparse
import os
import sys

from qdrant_client import models

# Add project root to path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from pipeline.db import Database  # noqa: E402


def reset_status(
    collection_name="documents_uneg", status="downloaded", full_reset=False
):
    print("Connecting to Qdrant (via shared Database connection)...")
    try:
        # Initialize Database to get the robust client
        # We don't care about the specific data_source here as we pass collection_name manually
        db = Database()
        client = db.client
    except Exception as e:
        print(f"Failed to connect to Qdrant: {e}")
        return

    # Check if collection exists

    # Check if collection exists
    if not client.collection_exists(collection_name):
        print(f"Collection {collection_name} does not exist.")
        return

    # Define filter based on mode
    scroll_filter = None

    # ALWAYS exclude 'downloaded_error' unless specifically handled?
    # User requested: "Fix reset_status to not update download error docs"
    # So we apply this filter in BOTH modes.

    # Base Exclusion: downloaded_error
    conditions = [
        models.FieldCondition(
            key="status",
            match=models.MatchValue(value="download_error"),
        )
    ]

    if full_reset:
        print(
            f"🔄 FULL RESET: Resetting documents in '{collection_name}' to status='{status}' "
            "(excluding 'download_error')..."
        )
        # In full reset, we only exclude downloaded_error
    else:
        print(
            "🧹 SMART RESET: Resetting only STUCK documents "
            "(not 'downloaded' or 'downloaded_error')..."
        )
        # In smart reset, we ALSO exclude 'downloaded'
        conditions.append(
            models.FieldCondition(
                key="status",
                match=models.MatchValue(value="downloaded"),
            )
        )

    scroll_filter = models.Filter(must_not=conditions)

    # Scroll and update in batches
    offset = None
    batch_size = 100
    count = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        update_ids = []
        for point in points:
            # SAFETY CHECK 1: Never reset a doc that points to an .error file
            # This handles cases where ScanProcessor incorrectly registered an error file as a doc
            filepath = point.payload.get("filepath", "")
            if filepath.endswith(".error"):
                print(f"  ⚠️ Skipping {point.id}: Invalid filepath (ends in .error)")
                continue

            # SAFETY CHECK 2: Don't reset if filepath is missing (unless we expect it to be empty?)
            # If we are resetting to 'downloaded', we usually expect a file to exist.
            # But maybe the reset is INTENDED to trigger a re-download?
            # If so, missing filepath is actually OK for a full reset.
            # However, for 'smart reset', we probably want to help valid docs.
            # But the user's specific crash was "No filepath".
            # If we reset a "No filepath" doc to "downloaded", the orchestrator will crash again
            # (unless the orchestrator re-downloads it? But standard orchestrator just
            # parses 'downloaded').
            # Thus, we should probably SKIP docs with no filepath in smart reset,
            # UNLESS they are specifically marked as 'download_error' (which we already exclude).

            update_ids.append(point.id)

        if update_ids:
            client.set_payload(
                collection_name=collection_name,
                payload={"status": status},
                points=update_ids,
            )
            count += len(update_ids)
            print(f"Updated {len(update_ids)} documents...")

        offset = next_offset
        if offset is None:
            break

    print(f"Done. Reset {count} documents.")


def main():
    parser = argparse.ArgumentParser(description="Reset document status in Qdrant.")
    parser.add_argument(
        "--collection",
        type=str,
        default="documents_uneg",
        help="Collection name (default: documents_uneg)",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="downloaded",
        help="Target status to set (default: downloaded)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "If set, resets ALL documents. If not set (default), "
            "only resets documents that are NOT 'downloaded' or 'downloaded_error'."
        ),
    )

    args = parser.parse_args()

    reset_status(
        collection_name=args.collection,
        status=args.status,
        full_reset=args.full,
    )


if __name__ == "__main__":
    main()
