#!/usr/bin/env python3
"""
Backfill multi-value fields in Qdrant.

Splits semicolon-separated string values (e.g. "Ethiopia; Kenya; Rwanda")
into proper arrays for faceting. Also copies src_ values to map_ fields
for documents that were indexed before the field mapping was applied.
"""

import os
import sys
from typing import Any, Dict, List, Union

from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_KEY = os.getenv("QDRANT_API_KEY", "")

# Core field -> map field name
CORE_FIELD_MAP = {
    "organization": "map_organization",
    "document_type": "map_document_type",
    "published_year": "map_published_year",
    "title": "map_title",
    "language": "map_language",
    "country": "map_country",
    "region": "map_region",
    "theme": "map_theme",
    "pdf_url": "map_pdf_url",
    "report_url": "map_report_url",
}

# Core field -> src field name (for backfilling map_ from src_)
CORE_TO_SRC = {
    "organization": None,  # fixed_value
    "title": "src_title_evaluation",
    "published_year": "src_completion_year",
    "document_type": "src_type",
    "language": "src_language",
    "country": "src_country",
    "region": "src_region",
    "theme": "src_topics",
    "pdf_url": "src_evaluation_report",
    "report_url": "src_evaluation_report",
}

# Fields that should never be split
SCALAR_FIELDS = {"title", "published_year", "pdf_url", "report_url", "organization"}


def split_if_multival(core_field: str, value: Any) -> Union[str, List[str]]:
    """Split semicolon-separated strings into lists for multi-value fields."""
    if core_field in SCALAR_FIELDS:
        return value
    if isinstance(value, str) and ";" in value:
        parts = [v.strip() for v in value.split(";") if v.strip()]
        return parts if len(parts) > 1 else (parts[0] if parts else value)
    return value


def backfill_collection(
    client: QdrantClient, collection: str, dry_run: bool = False
) -> int:
    """Backfill map_ fields and split multi-value strings in a collection."""
    print(f"\n{'=' * 60}")
    print(f"Processing {collection}")
    print(f"{'=' * 60}")

    updated = 0
    total = 0
    offset = None

    while True:
        points, offset = client.scroll(
            collection, limit=200, offset=offset, with_payload=True
        )
        if not points:
            break

        for p in points:
            total += 1
            payload_update: Dict[str, Any] = {}

            for core_field, map_field in CORE_FIELD_MAP.items():
                current_map = p.payload.get(map_field)
                src_field = CORE_TO_SRC.get(core_field)

                # Backfill missing map_ from src_
                if not current_map:
                    if core_field == "organization":
                        payload_update[map_field] = "WFP"
                    elif src_field and p.payload.get(src_field):
                        payload_update[map_field] = split_if_multival(
                            core_field, p.payload[src_field]
                        )
                # Split existing string multi-values
                elif isinstance(current_map, str) and ";" in current_map:
                    if core_field not in SCALAR_FIELDS:
                        val = split_if_multival(core_field, current_map)
                        if val != current_map:
                            payload_update[map_field] = val

            if payload_update:
                if not dry_run:
                    client.set_payload(collection, payload_update, points=[p.id])
                updated += 1

        if offset is None:
            break

    print(f"  Scanned {total} points, updated {updated}")
    return updated


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    data_source = "wfp"

    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            data_source = arg

    if dry_run:
        print("DRY RUN — no changes will be written")

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_KEY or None)

    docs_collection = f"documents_{data_source}"
    chunks_collection = f"chunks_{data_source}"

    backfill_collection(client, docs_collection, dry_run=dry_run)
    backfill_collection(client, chunks_collection, dry_run=dry_run)

    # Print verification
    print(f"\n{'=' * 60}")
    print("Verification")
    print(f"{'=' * 60}")
    for field in ["map_language", "map_country", "map_document_type"]:
        try:
            result = client.facet(docs_collection, key=field, limit=10)
            total = sum(h.count for h in result.hits)
            print(f"\n{field} ({total} docs):")
            for h in result.hits[:5]:
                print(f"  {h.value}: {h.count}")
        except Exception as e:
            print(f"\n{field}: error - {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
