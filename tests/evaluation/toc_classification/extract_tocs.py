#!/usr/bin/env python3
"""
Script to extract random TOCs to CSV for indexed docs.
Columns: Document Name, Agency, Year, TOC, TOC Categories

Usage:
    python3 tests/evaluation/toc_classification/extract_tocs.py --n 50 --output tocs.csv
"""

import argparse
import csv
import logging
import random
import sys

# Ensure we can import pipeline
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent.parent))  # noqa: E402

from pipeline.db import Database  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    print("Starting TOC extraction...", flush=True)
    parser = argparse.ArgumentParser(description="Extract random TOCs to CSV")
    parser.add_argument(
        "--n", type=int, default=50, help="Number of documents to extract (default: 50)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="tocs.csv",
        help="Output CSV file path (default: tocs.csv)",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="uneg",
        help="Data source/collection suffix (default: uneg)",
    )

    args = parser.parse_args()

    try:
        print(f"Connecting to Database (source={args.data_source})...", flush=True)
        db = Database(data_source=args.data_source)
        collection_name = db.documents_collection
        print(f"Connected to Qdrant. Collection: {collection_name}", flush=True)

        # Check connection by counting
        count = db.client.count(collection_name=collection_name).count
        print(f"Total documents in collection: {count}", flush=True)

        if count == 0:
            print("Collection is empty.", flush=True)
            return

        print("Fetching document IDs with TOCs...", flush=True)

        search_candidates = []
        next_offset = None

        # We need docs that have 'toc' and 'toc_classified'
        # Let's iterate.
        scanned = 0
        while True:
            # We fetch batches
            points, next_offset = db.client.scroll(
                collection_name=collection_name,
                limit=100,  # Smaller batches to show progress
                offset=next_offset,
                with_payload=True,
            )

            scanned += len(points)
            for point in points:
                payload = point.payload
                # Check for TOC existence.
                # Note: payload keys might be 'toc' or others based on schema.
                if payload.get("toc") is not None and payload.get("toc") != "":
                    # We also prefer those with toc_classified, but user asked for
                    # "TOC categories" which implies we should get them if they exist.
                    # If the requirement is "extract... for indexed docs", maybe we take
                    # any doc with TOC?
                    # Implementation plan said "Filters for documents that have
                    # toc_classified".
                    # I will stick to that to ensure we have categories.
                    if payload.get("toc_classified"):
                        search_candidates.append(payload)

            if scanned % 1000 == 0:
                print(
                    f"Scanned {scanned} docs. Found {len(search_candidates)} candidates so far...",
                    flush=True,
                )

            if next_offset is None:
                break

        total_candidates = len(search_candidates)
        print(
            f"Total candidates with TOC and Categories: {total_candidates}", flush=True
        )

        if total_candidates == 0:
            print(
                "No suitable documents found (must have 'toc' and 'toc_classified').",
                flush=True,
            )
            # Fallback: List a few docs to see what they look like?
            return

        # Randomly sample
        sample_size = min(args.n, total_candidates)
        print(f"Sampling {sample_size} documents...", flush=True)
        selected_docs = random.sample(search_candidates, sample_size)

        # Write CSV
        print(f"Writing to {args.output}...", flush=True)
        columns = ["Document Name", "Agency", "Year", "TOC", "TOC Categories"]

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            for doc in selected_docs:
                writer.writerow(
                    {
                        "Document Name": doc.get("title", ""),
                        "Agency": doc.get("agency", ""),
                        "Year": doc.get("year", ""),
                        "TOC": doc.get("toc", ""),
                        "TOC Categories": doc.get("toc_classified", ""),
                    }
                )

        print(f"Successfully wrote {sample_size} rows to {args.output}", flush=True)

    except Exception as e:
        print(f"CRITICAL ERROR: {e}", file=sys.stderr, flush=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
