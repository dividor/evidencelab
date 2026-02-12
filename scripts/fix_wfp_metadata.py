#!/usr/bin/env python3
"""Fix WFP metadata in Qdrant.

The WFP config.json field_mapping was pointing at wrong source field names
(copied from UNEG). This script reads the src_ fields already stored in
Qdrant and populates the correct map_ fields.

Mapping fixes:
  map_document_type  ← src_type           (was looking for evaluation_type)
  map_published_year ← src_completion_year (was looking for year)
  map_theme          ← src_topics         (was looking for theme)
  map_report_url     ← src_evaluation_report (was looking for report_url)
  map_country        ← src_coverage       (was looking for country)
  map_region         ← src_hq_regions     (was looking for region)
"""

import argparse
import time

from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
QDRANT_API_KEY = "31eff66a2391853e426f264c5edc5ca7969016591d29bb88cb135b80fbca44f2"  # pragma: allowlist secret  # noqa: E501
DOCS_COLLECTION = "documents_wfp"
CHUNKS_COLLECTION = "chunks_wfp"

# Mapping: map_field -> src_field
FIELD_FIX = {
    "map_document_type": "src_type",
    "map_published_year": "src_completion_year",
    "map_theme": "src_topics",
    "map_report_url": "src_evaluation_report",
    "map_country": "src_coverage",
    "map_region": "src_hq_regions",
}

SRC_FIELDS_NEEDED = list(FIELD_FIX.values())
PAYLOAD_FIELDS = list(FIELD_FIX.keys()) + SRC_FIELDS_NEEDED


def build_update_payload(doc_payload: dict) -> dict:
    """Build the corrected map_ payload from src_ fields."""
    updates = {}
    for map_key, src_key in FIELD_FIX.items():
        value = doc_payload.get(src_key)
        # published_year must be a string for Qdrant filtering
        if map_key == "map_published_year" and value is not None:
            value = str(int(value))
        updates[map_key] = value
    return updates


def fix_documents(client: QdrantClient, dry_run: bool = False) -> dict:
    """Fix map_ fields on all documents and return {doc_id: updates}."""
    doc_updates = {}
    offset = None
    batch = 0

    while True:
        result = client.scroll(
            collection_name=DOCS_COLLECTION,
            scroll_filter=None,
            limit=50,
            offset=offset,
            with_payload=PAYLOAD_FIELDS,
            with_vectors=False,
        )
        points, next_offset = result

        if not points:
            break

        for point in points:
            doc_id = point.id
            payload = point.payload or {}
            updates = build_update_payload(payload)
            doc_updates[str(doc_id)] = updates

            if not dry_run:
                client.set_payload(
                    collection_name=DOCS_COLLECTION,
                    payload=updates,
                    points=[doc_id],
                )

        batch += 1
        print(
            f"  Documents batch {batch}: processed {len(points)} docs (total {len(doc_updates)})"
        )

        if next_offset is None:
            break
        offset = next_offset

    return doc_updates


def fix_chunks(client: QdrantClient, doc_updates: dict, dry_run: bool = False):
    """Propagate map_ field fixes to all chunks."""
    total_chunks = 0

    for i, (doc_id, updates) in enumerate(doc_updates.items()):
        # Find all chunks for this document
        offset = None
        chunk_ids = []

        while True:
            result = client.scroll(
                collection_name=CHUNKS_COLLECTION,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchValue(value=doc_id),
                        )
                    ]
                ),
                limit=500,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            points, next_offset = result

            if not points:
                break

            chunk_ids.extend([p.id for p in points])

            if next_offset is None:
                break
            offset = next_offset

        if chunk_ids and not dry_run:
            # Batch update all chunks for this document
            client.set_payload(
                collection_name=CHUNKS_COLLECTION,
                payload=updates,
                points=chunk_ids,
            )

        total_chunks += len(chunk_ids)

        if (i + 1) % 25 == 0 or (i + 1) == len(doc_updates):
            print(
                f"  Chunks: processed {i + 1}/{len(doc_updates)} docs ({total_chunks} chunks)"
            )

    return total_chunks


def fix_postgres(doc_updates: dict, dry_run: bool = False):
    """Update map_ fields in Postgres sidecar."""
    try:
        import psycopg2
    except ImportError:
        print("  psycopg2 not available, skipping Postgres update")
        return 0

    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user="evidencelab",
        password="changeme",  # pragma: allowlist secret
        dbname="evidencelab",
    )
    cursor = conn.cursor()
    updated = 0

    for doc_id, updates in doc_updates.items():
        set_clauses = []
        values = []
        for col, val in updates.items():
            set_clauses.append(f"{col} = %s")
            values.append(val)
        values.append(doc_id)

        sql = f"UPDATE documents SET {', '.join(set_clauses)} WHERE doc_id = %s"
        if not dry_run:
            cursor.execute(sql, values)
            updated += cursor.rowcount

    if not dry_run:
        conn.commit()

    cursor.close()
    conn.close()
    return updated


def main():
    parser = argparse.ArgumentParser(description="Fix WFP metadata mapping in Qdrant")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    args = parser.parse_args()

    print(f"Connecting to Qdrant at {QDRANT_URL}")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    if args.dry_run:
        print("DRY RUN - no changes will be written\n")

    # Step 1: Fix documents
    print("Step 1: Fixing documents_wfp map_ fields...")
    t0 = time.time()
    doc_updates = fix_documents(client, dry_run=args.dry_run)
    print(f"  Done: {len(doc_updates)} documents in {time.time() - t0:.1f}s\n")

    # Show sample
    sample = list(doc_updates.items())[:3]
    for doc_id, updates in sample:
        print(f"  Sample {doc_id}:")
        for k, v in updates.items():
            print(f"    {k}: {v}")
        print()

    # Step 2: Fix chunks
    print("Step 2: Propagating fixes to chunks_wfp...")
    t0 = time.time()
    total_chunks = fix_chunks(client, doc_updates, dry_run=args.dry_run)
    print(f"  Done: {total_chunks} chunks in {time.time() - t0:.1f}s\n")

    # Step 3: Fix Postgres
    print("Step 3: Fixing Postgres documents table...")
    t0 = time.time()
    pg_updated = fix_postgres(doc_updates, dry_run=args.dry_run)
    print(f"  Done: {pg_updated} rows in {time.time() - t0:.1f}s\n")

    print("All done!")


if __name__ == "__main__":
    main()
