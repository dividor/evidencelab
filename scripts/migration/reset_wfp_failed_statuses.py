import argparse
import time

from qdrant_client import models

from pipeline.db import Database

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
    client = db.client
    collection_name = db.documents_collection

    status_filters = [
        models.FieldCondition(key="sys_status", match=models.MatchValue(value=status))
        for status in sorted(FAILED_STATUSES)
    ]
    scroll_filter = models.Filter(should=status_filters)

    offset = None
    total_matched = 0
    total_updated = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        if not points:
            break

        point_ids = [point.id for point in points]
        total_matched += len(point_ids)

        if not dry_run:
            client.set_payload(
                collection_name=collection_name,
                payload={
                    "sys_status": "downloaded",
                    "sys_error_message": None,
                    "sys_last_updated": time.time(),
                },
                points=point_ids,
                wait=True,
            )
            total_updated += len(point_ids)

        offset = next_offset
        if offset is None:
            break

    if dry_run:
        print(
            "Dry run complete. Matched %s documents in %s.",
            total_matched,
            collection_name,
        )
        return

    print(
        "Updated %s documents to sys_status='downloaded' in %s.",
        total_updated,
        collection_name,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reset WFP failed document statuses (parse/summarize/index/stopped) "
            "back to 'downloaded'."
        )
    )
    parser.add_argument(
        "--data-source",
        required=True,
        help="Data source key (required).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report matches without updating any documents.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for Qdrant updates (default: 200).",
    )

    args = parser.parse_args()
    reset_failed_statuses(
        data_source=args.data_source,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
