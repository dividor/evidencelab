"""Prepare a restored data source for rebuilding its search index.

After deploy/aws/scripts/restore-data.sh has loaded another deployment's
database, the data source's documents are marked `indexed`, but this
deployment's Qdrant collections don't hold them, or hold vectors from another
embedding model. This script:

1. empties and recreates the data source's Qdrant collections, and
2. marks every `indexed` document `tagged`, which the pipeline indexes next,
   without parsing, summarising or tagging it again:

       python -m pipeline.orchestrator --data-source <name> --skip-download \\
           --skip-scan --skip-parse --skip-summarize --skip-tag

Usage:
    python scripts/pipeline/prepare_reindex.py --data-source wfp [--dry-run]

--dry-run counts the documents and changes nothing.
"""

import argparse
import time
from typing import Callable

from pipeline.db.database import Database

FROM_STATUS = "indexed"
TO_STATUS = "tagged"


def prepare_reindex(
    data_source: str,
    dry_run: bool = False,
    database: Callable[..., Database] = Database,
) -> int:
    """Empty the data source's search index and mark its documents for indexing.

    Returns how many documents were (or, with DRY_RUN, would be) marked.
    """
    db = database(data_source=data_source)
    docs = db.pg.fetch_docs_by_status(status=FROM_STATUS)
    print(f"{len(docs)} documents are marked '{FROM_STATUS}' in {data_source}")
    if dry_run:
        print("Dry run: nothing changed")
        return len(docs)

    db.clear_all_data()
    print(
        f"Emptied the Qdrant collections {db.documents_collection} and {db.chunks_collection}"
    )
    for doc in docs:
        db.pg.merge_doc_sys_fields(
            doc_id=str(doc["id"]),
            sys_fields={"sys_status": TO_STATUS, "sys_last_updated": time.time()},
        )
    print(
        f"Marked {len(docs)} documents '{TO_STATUS}': the pipeline's next run indexes them"
    )
    return len(docs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Empty a data source's search index and mark its documents for indexing."
    )
    parser.add_argument(
        "--data-source", required=True, help="its folder name, e.g. wfp"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="count only; change nothing"
    )
    args = parser.parse_args()
    prepare_reindex(args.data_source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
