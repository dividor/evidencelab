"""Helpers for integration test data cleanup."""

import json
from pathlib import Path
from typing import Optional

from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

from pipeline.db import Database


def purge_test_document_data(
    *,
    data_source: str = "uneg",
    title: Optional[str] = None,
    metadata_path: Optional[str] = None,
) -> int:
    """Remove all docs/chunks matching the test document title."""

    if title is None and metadata_path:
        metadata = json.loads(Path(metadata_path).read_text())
        title = metadata.get("title")

    if not title:
        raise ValueError("Title is required to purge test document data.")

    def normalize_title(value: str) -> str:
        return " ".join(value.split())

    db = Database(data_source=data_source)
    normalized_expected_title = normalize_title(title)

    matching_points = []
    next_offset = None
    while True:
        points, next_offset = db.client.scroll(
            collection_name=db.documents_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="map_title", match=MatchText(text=title))]
            ),
            limit=200,
            offset=next_offset,
            with_payload=True,
        )
        for point in points:
            point_title = point.payload.get("map_title", "") or ""
            if normalize_title(point_title) == normalized_expected_title:
                matching_points.append(point)
        if next_offset is None:
            break

    delete_doc_ids = [point.id for point in matching_points]
    if not delete_doc_ids:
        print(f"\n🧹 No existing documents found for title: {title}")
    else:
        print(f"\n🧹 Removing {len(delete_doc_ids)} document(s) for title: {title}")
        for doc_id in delete_doc_ids:
            db.client.delete(
                collection_name=db.chunks_collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id", match=MatchValue(value=str(doc_id))
                        )
                    ]
                ),
            )

    chunk_ids = []
    next_offset = None
    while True:
        points, next_offset = db.client.scroll(
            collection_name=db.chunks_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="map_title", match=MatchValue(value=title))]
            ),
            limit=200,
            offset=next_offset,
        )
        chunk_ids.extend([point.id for point in points])
        if next_offset is None:
            break

    if chunk_ids:
        db.client.delete(
            collection_name=db.chunks_collection,
            points_selector=chunk_ids,
            wait=True,
        )

    if delete_doc_ids:
        db.client.delete(
            collection_name=db.documents_collection,
            points_selector=delete_doc_ids,
        )

    pg_deleted = db.pg.delete_docs_by_title(title)
    if pg_deleted:
        print(f"🧹 Removed {len(pg_deleted)} Postgres doc(s) for title: {title}")
    return len(delete_doc_ids)
