"""CLI entrypoint for tagger."""

import argparse
import logging

from pipeline.db import Database
from pipeline.processors.tagging.tagger_processor import TaggerProcessor


def main() -> None:
    """Run tagger over documents from CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Tag chunks with semantic labels")
    parser.add_argument(
        "--data-source", default="uneg", help="Data source to process (default: uneg)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of documents to process"
    )
    parser.add_argument(
        "--doc-id", default=None, help="Process a specific document by ID"
    )

    args = parser.parse_args()

    with TaggerProcessor(data_source=args.data_source) as tagger:
        if args.doc_id:
            db = Database(data_source=args.data_source)
            doc = db.get_document(args.doc_id)
            if doc:
                doc["id"] = args.doc_id
                result = tagger.process_document(doc)
                print(f"Result: {result}")
            else:
                print(f"Document {args.doc_id} not found")
        else:
            result = tagger.process_all_documents(limit=args.limit)
            print("\nTagging complete:")
            print(f"  Documents processed: {result['documents_processed']}")
            print(f"  Documents skipped: {result['documents_skipped']}")
            print(f"  Total chunks updated: {result['total_chunks_updated']}")
