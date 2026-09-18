import argparse
import time
from typing import List

from pipeline.db.database import Database

FAILED_STATUSES = {
    "parse_failed",
    "summarize_failed",
    "index_failed",
    "stopped",
}

# Statuses a document only holds while a stage is running. A document left in
# one of these is the residue of a run that died; nothing will pick it up
# again, because every stage selects on the status that precedes it.
STUCK_STATUSES = {
    "parsing",
    "summarizing",
    "tagging",
    "indexing",
}

RESET_FIELDS = {
    "sys_status": "downloaded",
    "sys_error_message": None,
}


def _reset_docs(db: Database, doc_ids: List[str]) -> None:
    for doc_id in doc_ids:
        db.pg.merge_doc_sys_fields(
            doc_id=doc_id,
            sys_fields={**RESET_FIELDS, "sys_last_updated": time.time()},
        )


def reset_failed_statuses(
    data_source: str,
    dry_run: bool = False,
    batch_size: int = 200,
    include_stuck: bool = False,
    include_empty_indexed: bool = False,
) -> None:
    db = Database(data_source=data_source)

    statuses = set(FAILED_STATUSES)
    if include_stuck:
        statuses |= STUCK_STATUSES

    total_found = 0
    total_updated = 0

    for status in sorted(statuses):
        print(f"Checking status: {status}...")
        docs = db.pg.fetch_docs_by_status(status=status)
        if not docs:
            continue

        count = len(docs)
        total_found += count
        print(f"  Found {count} documents with status '{status}'")

        if dry_run:
            continue

        _reset_docs(db, [str(doc["id"]) for doc in docs])
        total_updated += count

    if include_empty_indexed:
        print("Checking documents marked indexed with no chunks...")
        doc_ids = db.pg.fetch_doc_ids_indexed_without_chunks()
        if doc_ids:
            total_found += len(doc_ids)
            print(f"  Found {len(doc_ids)} documents marked indexed with no chunks")
            if not dry_run:
                _reset_docs(db, doc_ids)
                total_updated += len(doc_ids)

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
    parser.add_argument(
        "--include-stuck",
        action="store_true",
        help=(
            "Also reset documents left mid-stage by an interrupted run "
            f"({', '.join(sorted(STUCK_STATUSES))}). Only use this when no "
            "pipeline run is active, or documents being processed right now "
            "will be reset underneath it."
        ),
    )
    parser.add_argument(
        "--include-empty-indexed",
        action="store_true",
        help=(
            "Also reset documents marked indexed that have no chunks. These "
            "answer no search and are skipped by every later run."
        ),
    )

    args = parser.parse_args()
    reset_failed_statuses(
        data_source=args.data_source,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        include_stuck=args.include_stuck,
        include_empty_indexed=args.include_empty_indexed,
    )


if __name__ == "__main__":
    main()
