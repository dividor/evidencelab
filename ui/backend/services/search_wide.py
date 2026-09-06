"""Wide search: spread results across documents with Qdrant grouped queries.

Instead of a flat top-N of chunks (where one document with many strong
passages can fill the list), a wide search asks Qdrant for ``doc_limit``
documents with at most ``group_size`` chunks each, documents ordered by their
best-scoring chunk. Hybrid requests run one grouped query per vector type and
fuse them at document level with the same weighted reciprocal-rank fusion the
chunk-level hybrid search uses, so the caller's dense/keyword balance holds.
"""

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from pipeline.db import SPARSE_VECTOR_NAME
from pipeline.db.database import Database

logger = logging.getLogger(__name__)

# Wide search groups chunks by this payload field. It is the ingest-assigned
# document id, present and keyword-indexed on every chunk.
WIDE_GROUP_BY_FIELD = "doc_id"
WIDE_RRF_K = 60


def _run_grouped_query(
    db: Database,
    collection: str,
    query: Any,
    using: str,
    query_filter: models.Filter,
    doc_limit: int,
    group_size: int,
    payload_fields: Optional[List[str]],
    search_params: Optional[models.SearchParams] = None,
) -> List[Any]:
    """One Qdrant grouped query: up to ``doc_limit`` documents, each with at
    most ``group_size`` chunks, documents ordered by their best-scoring chunk."""
    kwargs: Dict[str, Any] = {
        "collection_name": collection,
        "group_by": WIDE_GROUP_BY_FIELD,
        "query": query,
        "using": using,
        "query_filter": query_filter,
        "limit": doc_limit,
        "group_size": group_size,
        "with_payload": payload_fields if payload_fields else True,
    }
    if search_params is not None:
        kwargs["search_params"] = search_params
    return db.client.query_points_groups(**kwargs).groups


def _flatten_groups(groups: List[Any]) -> List[Any]:
    """Document-major list of hits, in group order, keeping Qdrant scores."""
    return [hit for group in groups for hit in group.hits]


def _merge_grouped_hybrid(
    dense_groups: List[Any],
    sparse_groups: List[Any],
    weight: float,
    doc_limit: int,
    group_size: int,
) -> List[Any]:
    """Merge dense and sparse grouped results at document level with the same
    weighted reciprocal-rank fusion the chunk-level hybrid search uses, so wide
    mode keeps the caller's dense/keyword balance. Each document keeps at most
    ``group_size`` chunks (dense hits first); every chunk carries its
    document's fused score."""
    doc_scores: Dict[str, float] = defaultdict(float)
    doc_hits: Dict[str, Dict[str, Any]] = {}
    for rank, group in enumerate(dense_groups, 1):
        doc_id = str(group.id)
        doc_scores[doc_id] += weight / (WIDE_RRF_K + rank)
        hits = doc_hits.setdefault(doc_id, {})
        for hit in group.hits:
            hits.setdefault(str(hit.id), hit)
    for rank, group in enumerate(sparse_groups, 1):
        doc_id = str(group.id)
        doc_scores[doc_id] += (1.0 - weight) / (WIDE_RRF_K + rank)
        hits = doc_hits.setdefault(doc_id, {})
        for hit in group.hits:
            hits.setdefault(str(hit.id), hit)
    ranked_docs = sorted(doc_scores, key=lambda d: doc_scores[d], reverse=True)[
        :doc_limit
    ]
    merged: List[Any] = []
    for doc_id in ranked_docs:
        for hit in list(doc_hits[doc_id].values())[:group_size]:
            hit.score = doc_scores[doc_id]
            merged.append(hit)
    return merged


def run_wide_search(
    db: Database,
    collection: str,
    dense_vec,
    sparse_vec,
    dense_model: str,
    query_filter: models.Filter,
    payload_fields: Optional[List[str]],
    weight: float,
    doc_limit: int,
    group_size: int,
    search_params: Optional[models.SearchParams] = None,
) -> List[Any]:
    """Wide search: spread results across documents using Qdrant grouped
    queries instead of a flat top-N. Returns ``doc_limit`` documents with at
    most ``group_size`` chunks each, as a flat document-major list."""
    t_start = time.time()
    dense_query = dense_vec.tolist()
    sparse_query = models.SparseVector(
        indices=sparse_vec.indices.tolist(), values=sparse_vec.values.tolist()
    )
    if weight >= 0.99:
        groups = _run_grouped_query(
            db,
            collection,
            dense_query,
            dense_model,
            query_filter,
            doc_limit,
            group_size,
            payload_fields,
            search_params=search_params,
        )
        result = _flatten_groups(groups)
    elif weight <= 0.01:
        groups = _run_grouped_query(
            db,
            collection,
            sparse_query,
            SPARSE_VECTOR_NAME,
            query_filter,
            doc_limit,
            group_size,
            payload_fields,
        )
        result = _flatten_groups(groups)
    else:
        # Fetch twice the documents from each side so the fused ranking has
        # candidates that only one vector type surfaced.
        dense_groups = _run_grouped_query(
            db,
            collection,
            dense_query,
            dense_model,
            query_filter,
            doc_limit * 2,
            group_size,
            payload_fields,
            search_params=search_params,
        )
        sparse_groups = _run_grouped_query(
            db,
            collection,
            sparse_query,
            SPARSE_VECTOR_NAME,
            query_filter,
            doc_limit * 2,
            group_size,
            payload_fields,
        )
        result = _merge_grouped_hybrid(
            dense_groups, sparse_groups, weight, doc_limit, group_size
        )
    logger.info(
        "[TIMING] Qdrant grouped queries (wide): %.3fs (%d chunks, docs<=%d, per_doc<=%d)",
        time.time() - t_start,
        len(result),
        doc_limit,
        group_size,
    )
    return result
