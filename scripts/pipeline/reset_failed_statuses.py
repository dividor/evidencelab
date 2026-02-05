import argparse
import time

from pipeline.db.database import Database

FAILED_STATUSES = {
    "parse_failed",
    "summarize_failed",
    "index_failed",
    "stopped",
}


def reset_failed_statuses(
    data_source: str, dry_run: bool = False, batch_size: int = 200
) -> None:
    db = Database(data_source=data_source)

    total_found = 0
    total_updated = 0

    for status in FAILED_STATUSES:
        print(f"Checking status: {status}...")
        try:
            # We don't care about year filtering here, just get all failed
            docs = db.pg.fetch_docs_by_status(status=status)
            if not docs:
                continue

            count = len(docs)
            total_found += count
            print(f"  Found {count} documents with status '{status}'")

            if dry_run:
                continue

            for doc in docs:
                db.pg.merge_doc_sys_fields(
                    doc_id=str(doc["id"]),
                    sys_fields={
                        "sys_status": "downloaded",
                        "sys_error_message": None,
                        "sys_last_updated": time.time(),
                    },
                )
            total_updated += count

        except Exception as e:
            print(f"Error checking status {status}: {e}")

    if dry_run:
        print(f"Dry run complete. Found {total_found} documents to reset.")
        return

    print(f"Updated {total_updated} documents to sys_status='downloaded'.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset failed document statuses back to 'downloaded' via Postgres."
    )
    parser.add_argument(
        "--data-source",
        required=True,
        help="Data source key (required).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report matches without updating.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Unused in Postgres implementation.",
    )

    args = parser.parse_args()
    reset_failed_statuses(
        data_source=args.data_source,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
