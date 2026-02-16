import argparse
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from pipeline.db import (  # noqa: E402
    DB_VECTORS,
    DEFAULT_DATA_SOURCE,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    SUPPORTED_RERANK_MODELS,
    Database,
    PostgresClient,
    get_db,
    get_field_mapping,
    get_filter_fields,
)
from pipeline.utilities.embedding_client import RemoteEmbeddingClient  # noqa: E402
from ui.backend.services import search_models  # noqa: E402
from ui.backend.utils.language_codes import LANGUAGE_NAMES  # noqa: E402

# Add parent directory to path


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

SYSTEM_FIELD_MAP = {
    "status": "sys_status",
    "file_format": "sys_file_format",
    "full_summary": "sys_full_summary",
}


def _language_uses_sys(data_source: Optional[str]) -> bool:
    source = data_source or DEFAULT_DATA_SOURCE
    field_mapping = get_field_mapping(source)
    return field_mapping.get("language") == "sys_language"


def _resolve_storage_field(field: str, data_source: Optional[str]) -> str:
    if field == "language" and _language_uses_sys(data_source):
        return "sys_language"
    return map_field_to_storage(field)


def map_field_to_storage(field: str) -> str:
    if field.startswith("map_") or field.startswith("sys_"):
        return field
    if field in SYSTEM_FIELD_MAP:
        return SYSTEM_FIELD_MAP[field]
    return CORE_FIELD_MAP.get(field, field)


def map_filters_to_storage(
    filters: dict | None, data_source: Optional[str] = None
) -> dict | None:
    if not filters:
        return filters
    return {_resolve_storage_field(k, data_source): v for k, v in filters.items()}


# Load search configuration
DENSE_MODEL = search_models.DENSE_MODEL
SPARSE_MODEL = search_models.SPARSE_MODEL
USE_EMBEDDING_SERVER = search_models.USE_EMBEDDING_SERVER
EMBEDDING_API_URL = search_models.EMBEDDING_API_URL
RERANK_MODEL = search_models.RERANK_MODEL
SEARCH_DENSE_WEIGHT = search_models.SEARCH_DENSE_WEIGHT
SEARCH_HNSW_EF = search_models.SEARCH_HNSW_EF
SEARCH_EXACT = search_models.SEARCH_EXACT
QUANTIZATION_RESCORE = search_models.QUANTIZATION_RESCORE
SEARCH_FETCH_LIMIT = search_models.SEARCH_FETCH_LIMIT

# Minimal payload fields to request from Qdrant during search.
# Heavy fields (sys_text, sys_bbox, sys_tables, etc.) are fetched from
# PostgreSQL instead, avoiding large payload transfers from Qdrant.
SEARCH_PAYLOAD_FIELDS = ["doc_id", "sys_doc_id", "tag_section_type"]

_resolved_embedding_api_url: Optional[str] = None


def _normalize_embedding_url(url: str) -> str:
    return search_models._normalize_embedding_url(url)


def _embedding_server_healthy(base_url: str) -> bool:
    return search_models._embedding_server_healthy(base_url)


def _reset_cached_embedding_url(env_url: Optional[str]) -> None:
    return search_models._reset_cached_embedding_url(env_url)


def _build_embedding_candidates(
    env_url: Optional[str],
) -> tuple[List[str], Optional[str]]:
    return search_models._build_embedding_candidates(env_url)


def get_embedding_api_url() -> str:
    return search_models.get_embedding_api_url()


# Rerank model key from config, fallback to default
RERANK_MODEL = search_models.RERANK_MODEL
SEARCH_DENSE_WEIGHT = search_models.SEARCH_DENSE_WEIGHT

# E5 models require special prefixes for queries and passages
IS_E5_MODEL = "e5" in DENSE_MODEL.lower()


def add_query_prefix(text: str, model_name: str = "") -> str:
    return search_models.add_query_prefix(text, model_name)


SEARCH_HNSW_EF = search_models.SEARCH_HNSW_EF
SEARCH_EXACT = search_models.SEARCH_EXACT
QUANTIZATION_RESCORE = search_models.QUANTIZATION_RESCORE

# Cache models for reuse
_dense_models_cache: dict[str, Any] = {}
_dense_models_lock = threading.Lock()
_sparse_model = None
_sparse_model_lock = threading.Lock()
_rerank_models_cache: dict[str, Any] = {}
_rerank_models_lock = threading.Lock()


def get_dense_model(vector_name: str = None):
    return search_models.get_dense_model(
        vector_name,
        db_vectors=DB_VECTORS,
        cache=_dense_models_cache,
        lock=_dense_models_lock,
        dense_model=DENSE_VECTOR_NAME,
    )


def get_sparse_model():
    global _sparse_model
    if _sparse_model is not None:
        return _sparse_model
    with _sparse_model_lock:
        if _sparse_model is None:
            _sparse_model = search_models.get_sparse_model(model_name=SPARSE_MODEL)
    return _sparse_model


def get_models(dense_vector_name: str = None):
    return get_dense_model(dense_vector_name), get_sparse_model()


def _resolve_rerank_model_name(model_key: Optional[str]) -> str:
    return search_models._resolve_rerank_model_name(
        model_key, rerank_model=RERANK_MODEL
    )


def _get_rerank_model_config(model_key: Optional[str]) -> Dict[str, Any]:
    return search_models._get_rerank_model_config(
        model_key,
        supported_rerank_models=SUPPORTED_RERANK_MODELS,
        rerank_model=RERANK_MODEL,
    )


def _is_azure_foundry_reranker(config: Dict[str, Any]) -> bool:
    return search_models._is_azure_foundry_reranker(config)


def _get_azure_foundry_rerank_endpoint(
    deployment: str, config: Optional[Dict[str, Any]] = None
) -> str:
    return search_models._get_azure_foundry_rerank_endpoint(config, deployment)


def _get_azure_foundry_api_key() -> str:
    return search_models._get_azure_foundry_api_key()


def _scores_from_results(results: Any, doc_count: int) -> Optional[List[float]]:
    return search_models._scores_from_results(results, doc_count)


def _scores_from_list(scores: Any) -> Optional[List[float]]:
    return search_models._scores_from_list(scores)


def _scores_from_data(data: Any, doc_count: int) -> Optional[List[float]]:
    return search_models._scores_from_data(data, doc_count)


def _parse_azure_rerank_response(
    response_json: Dict[str, Any], doc_count: int
) -> List[float]:
    return search_models._parse_azure_rerank_response(response_json, doc_count)


def _rerank_with_azure_foundry(
    query: str,
    documents: List[str],
    deployment: str,
    config: Dict[str, Any],
) -> List[float]:
    return search_models._rerank_with_azure_foundry(
        query=query,
        documents=documents,
        deployment=deployment,
        config=config,
    )


def get_rerank_model(model_key: Optional[str] = None):
    return search_models.get_rerank_model(
        model_key,
        supported_rerank_models=SUPPORTED_RERANK_MODELS,
        cache=_rerank_models_cache,
        lock=_rerank_models_lock,
        rerank_model=RERANK_MODEL,
    )


def rerank_results(
    query: str,
    results: List[Any],
    limit: Optional[int] = None,
    max_rerank_candidates: int = 0,
    rerank_model: Optional[str] = None,
    chunk_cache: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    return search_models.rerank_results(
        query=query,
        results=results,
        rerank_model=rerank_model,
        limit=limit,
        chunk_cache=chunk_cache,
        max_rerank_candidates=max_rerank_candidates,
        supported_rerank_models=SUPPORTED_RERANK_MODELS,
        rerank_model_loader=get_rerank_model,
    )


def apply_recency_boost(
    results: List[Any],
    recency_weight: float = 0.15,
    scale_days: int = 365,
) -> List[Any]:
    return search_models.apply_recency_boost(
        results=results,
        recency_weight=recency_weight,
        scale_days=scale_days,
    )


def _resolve_dense_model_name(dense_model: Optional[str]) -> str:
    model_name = dense_model or DENSE_VECTOR_NAME
    if model_name not in DB_VECTORS:
        logger.warning(
            "Requested model %s not in DB_VECTORS, using default %s",
            model_name,
            DENSE_VECTOR_NAME,
        )
        return DENSE_VECTOR_NAME
    return model_name


def _resolve_dense_weight(
    query: str, dense_weight: Optional[float], keyword_boost_short_queries: bool
) -> float:
    weight = dense_weight if dense_weight is not None else SEARCH_DENSE_WEIGHT
    if keyword_boost_short_queries and query.strip():
        word_count = len(query.strip().split())
        if word_count <= 2:
            short_query_weight = float(os.getenv("SHORT_QUERY_DENSE_WEIGHT", "0.25"))
            logger.info(
                "Short query detected (%s words), using dense_weight=%s (keyword boost enabled)",
                word_count,
                short_query_weight,
            )
            weight = short_query_weight
    return weight


def _get_search_db(db: Optional[Database], data_source: Optional[str]) -> Database:
    return db if db is not None else get_db(data_source)


def _ensure_embedding_server(dense_embedding_model: Any) -> None:
    if USE_EMBEDDING_SERVER and isinstance(
        dense_embedding_model, RemoteEmbeddingClient
    ):
        if not _embedding_server_healthy(dense_embedding_model.base_url):
            fallback_url = get_embedding_api_url()
            logger.warning(
                "Embedding server %s is not reachable; switching to %s",
                dense_embedding_model.base_url,
                fallback_url,
            )
            dense_embedding_model.base_url = fallback_url


def _embed_query_vectors(
    query: str,
    dense_model: str,
    dense_embedding_model: Any,
    sparse_embedding_model: Any,
):
    t_embed_start = time.time()
    model_id = DB_VECTORS[dense_model]["model_id"]
    dense_query = add_query_prefix(query, str(model_id))

    if isinstance(dense_embedding_model, RemoteEmbeddingClient):
        dense_vec = list(dense_embedding_model.embed([query]))[0]
    else:
        dense_vec = list(dense_embedding_model.embed([dense_query]))[0]

    sparse_vec = list(sparse_embedding_model.embed([query]))[0]
    t_embed_end = time.time()
    logger.info("[TIMING] Embedding generation: %.3fs", t_embed_end - t_embed_start)
    return dense_vec, sparse_vec


def _split_filter_values(value: Any) -> Optional[List[str]]:
    if isinstance(value, str) and "," in value:
        values = [item.strip() for item in value.split(",") if item.strip()]
        if values:
            return values
    return None


def _as_multi_values(value: Any) -> Optional[List[str]]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return _split_filter_values(value)


def _build_filter_condition(
    field: str, value: Any, text_match_fields: set[str]
) -> Optional[models.FieldCondition]:
    if value is None:
        return None
    if field in text_match_fields:
        return models.FieldCondition(
            key=field,
            match=models.MatchText(text=value),
        )
    multi_values = _as_multi_values(value)
    return models.FieldCondition(
        key=field,
        match=(
            models.MatchAny(any=multi_values)
            if multi_values
            else models.MatchValue(value=value)
        ),
    )


def _build_query_filter(
    filters: Optional[dict],
    section_types: Optional[List[str]],
    data_source: Optional[str],
) -> models.Filter:
    must_conditions: List[models.Condition] = []
    must_not_conditions: List[models.Condition] = []
    should_conditions: List[models.Condition] = []

    if section_types:
        must_conditions.append(
            models.FieldCondition(
                key="tag_section_type",
                match=models.MatchAny(any=section_types),
            )
        )

    filters = map_filters_to_storage(filters, data_source=data_source)
    if filters:
        text_match_fields = {"map_title"}
        for field, value in filters.items():
            if field == "doc_id":
                # doc_id filter must be required, but we need to check both doc_id and sys_doc_id
                # Create a nested filter: MUST(doc_id=X OR sys_doc_id=X)
                doc_id_should_conditions = []
                multi_values = _as_multi_values(value)
                if multi_values:
                    doc_id_should_conditions.append(
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchAny(any=multi_values),
                        )
                    )
                    doc_id_should_conditions.append(
                        models.FieldCondition(
                            key="sys_doc_id",
                            match=models.MatchAny(any=multi_values),
                        )
                    )
                else:
                    doc_id_should_conditions.append(
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchValue(value=value),
                        )
                    )
                    doc_id_should_conditions.append(
                        models.FieldCondition(
                            key="sys_doc_id",
                            match=models.MatchValue(value=value),
                        )
                    )
                # Wrap the should conditions in a nested filter and add to must
                must_conditions.append(models.Filter(should=doc_id_should_conditions))
                continue
            condition = _build_filter_condition(field, value, text_match_fields)
            if condition:
                must_conditions.append(condition)

    return models.Filter(
        must=must_conditions if must_conditions else None,
        must_not=must_not_conditions,
        should=should_conditions if should_conditions else None,
    )


def _compute_fetch_limit(limit: int, min_chunk_size: int) -> int:
    if SEARCH_FETCH_LIMIT >= 1:
        return SEARCH_FETCH_LIMIT
    if min_chunk_size > 0:
        return int(limit * 2.0)
    return limit


def _build_search_params() -> models.SearchParams:
    return models.SearchParams(
        hnsw_ef=SEARCH_HNSW_EF,
        exact=SEARCH_EXACT,
        quantization=models.QuantizationSearchParams(
            rescore=QUANTIZATION_RESCORE,
        ),
    )


def _run_dense_search(
    db: Database,
    collection: str,
    dense_vec,
    dense_model: str,
    query_filter: models.Filter,
    fetch_limit: int,
    payload_fields: Optional[List[str]],
):
    query_response = db.client.query_points(
        collection_name=collection,
        query=dense_vec.tolist(),
        using=dense_model,
        query_filter=query_filter,
        limit=fetch_limit,
        with_payload=payload_fields if payload_fields else True,
        search_params=_build_search_params(),
    )
    return query_response.points


def _run_sparse_search(
    db: Database,
    collection: str,
    sparse_vec,
    query_filter: models.Filter,
    fetch_limit: int,
    payload_fields: Optional[List[str]],
):
    query_response = db.client.query_points(
        collection_name=collection,
        query=models.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist(),
        ),
        using=SPARSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=fetch_limit,
        with_payload=payload_fields if payload_fields else True,
    )
    return query_response.points


def _merge_hybrid_results(
    dense_results: List[Any],
    sparse_results: List[Any],
    weight: float,
    limit: int,
) -> List[Any]:
    rrf_k = 60
    chunk_scores = defaultdict(  # type: ignore[var-annotated]
        lambda: {"dense_score": 0, "sparse_score": 0, "rrf_score": 0, "point": None}
    )

    for rank, result in enumerate(dense_results, 1):
        chunk_id = str(result.id)
        chunk_scores[chunk_id]["dense_score"] = result.score  # type: ignore[assignment]
        chunk_scores[chunk_id]["rrf_score"] += weight / (rrf_k + rank)  # type: ignore[assignment]
        chunk_scores[chunk_id]["point"] = result

    sparse_weight = 1.0 - weight
    for rank, result in enumerate(sparse_results, 1):
        chunk_id = str(result.id)
        chunk_scores[chunk_id]["sparse_score"] = result.score  # type: ignore[assignment]
        chunk_scores[chunk_id]["rrf_score"] += sparse_weight / (rrf_k + rank)  # type: ignore[assignment]  # noqa: E501
        if chunk_scores[chunk_id]["point"] is None:
            chunk_scores[chunk_id]["point"] = result  # type: ignore[assignment]

    sorted_chunks = sorted(
        chunk_scores.values(), key=lambda x: x["rrf_score"], reverse=True
    )[:limit]

    search_result = []
    for chunk_data in sorted_chunks:
        point = chunk_data["point"]
        point.score = chunk_data["rrf_score"]  # type: ignore[attr-defined]
        search_result.append(point)  # type: ignore[arg-type]
    return search_result


def _run_hybrid_search(
    db: Database,
    collection: str,
    dense_vec,
    sparse_vec,
    dense_model: str,
    query_filter: models.Filter,
    fetch_limit: int,
    payload_fields: Optional[List[str]],
    weight: float,
    limit: int,
):
    t_qdrant_start = time.time()
    dense_results = _run_dense_search(
        db,
        collection,
        dense_vec,
        dense_model,
        query_filter,
        fetch_limit * 3,
        payload_fields,
    )
    t_dense_end = time.time()
    sparse_results = _run_sparse_search(
        db,
        collection,
        sparse_vec,
        query_filter,
        fetch_limit * 3,
        payload_fields,
    )
    t_qdrant_end = time.time()
    logger.info(
        "[TIMING] Qdrant queries (hybrid): %.3fs (dense=%.3fs, sparse=%.3fs)",
        t_qdrant_end - t_qdrant_start,
        t_dense_end - t_qdrant_start,
        t_qdrant_end - t_dense_end,
    )
    return _merge_hybrid_results(dense_results, sparse_results, weight, limit)


def _filter_min_chunk_size(
    results: List[Any],
    min_chunk_size: int,
    chunk_cache: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    if min_chunk_size <= 0:
        return results
    filtered_results = []
    for result in results:
        chunk_payload = (
            chunk_cache.get(str(result.id), {}) if chunk_cache is not None else {}
        )
        text = chunk_payload.get("sys_text") or result.payload.get("sys_text", "")
        if len(text) >= min_chunk_size:
            filtered_results.append(result)
    logger.info(
        "Filtered by size (min=%s): %s results remaining",
        min_chunk_size,
        len(filtered_results),
    )
    return filtered_results


def _apply_post_search_adjustments(
    search_result: List[Any],
    query: str,
    limit: int,
    rerank: bool,
    rerank_model: Optional[str],
    recency_boost: bool,
    recency_weight: float,
    recency_scale_days: int,
    chunk_cache: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    if recency_boost and search_result:
        search_result = apply_recency_boost(
            search_result, recency_weight=recency_weight, scale_days=recency_scale_days
        )
    if rerank and search_result:
        search_result = rerank_results(
            query,
            search_result,
            limit=limit,
            rerank_model=rerank_model,
            chunk_cache=chunk_cache,
        )
    if limit and len(search_result) > limit:
        return search_result[:limit]
    return search_result


def _filter_section_types(
    results: List[Any],
    section_types: Optional[List[str]],
    chunk_cache: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    if not section_types:
        return results
    allowed = {section.strip().lower() for section in section_types if section}
    if not allowed:
        return results
    filtered = []
    for result in results:
        chunk_payload = (
            chunk_cache.get(str(result.id), {}) if chunk_cache is not None else {}
        )
        section = chunk_payload.get("tag_section_type") or result.payload.get(
            "tag_section_type"
        )
        if section and str(section).strip().lower() in allowed:
            filtered.append(result)
    return filtered


def search_chunks(
    query: str,
    limit: int = 10,
    dense_weight: float = None,
    db: Database = None,
    data_source: str | None = None,
    filters: dict = None,
    rerank: bool = False,
    rerank_model: Optional[str] = None,
    recency_boost: bool = False,
    recency_weight: float = 0.15,
    recency_scale_days: int = 365,
    section_types: List[str] = None,
    keyword_boost_short_queries: bool = True,
    min_chunk_size: int = 0,
    dense_model: str = None,
    payload_fields: List[str] = None,
) -> List[Any]:
    """
    Hybrid search combining semantic (dense) and keyword (sparse) vectors.
    The balance is controlled by dense_weight parameter (or SEARCH_DENSE_WEIGHT if not provided):
    - 1.0 = Pure semantic search (dense only)
    - 0.8 = 80% semantic, 20% keyword
    - 0.5 = Balanced hybrid
    - 0.0 = Pure keyword/BM25 search (sparse only)

    All filters are applied directly in Qdrant for proper ranking within filtered results.

    Args:
        query: Search query string
        limit: Maximum results to return
        dense_weight: Optional weight for dense search (0.0-1.0). If None, uses SEARCH_DENSE_WEIGHT.
        db: Database instance. If None, uses default from get_db().
        filters: Dictionary of field_name -> value for exact match filtering in Qdrant.
                 Special handling: 'agency' maps to 'organization' field in Qdrant.
        rerank: If True, rerank results using cross-encoder reranker model.
        rerank_model: Optional reranker model key to use.
        recency_boost: If True, apply recency boosting based on publication date.
        recency_weight: Weight for recency boost (0.0-1.0). Higher = more weight on recency.
        recency_scale_days: Decay scale in days. Results older than this decay to ~37% of max boost.
        section_types: List of section types to filter by (e.g., ["findings", "recommendations"]).
                      If None, no section type filtering is applied.
        keyword_boost_short_queries: If True, automatically use lower dense weight for short queries
                                     (≤2 words). Uses SHORT_QUERY_DENSE_WEIGHT from env.
        min_chunk_size: Minimum character length for a chunk to be included in results.
                        If > 0, chunks shorter than this will be filtered out.
        payload_fields: Optional list of fields to include in the payload.
                        If provided, only these fields are returned.
                        If None, full payload is returned.


    Returns:
        List of Qdrant ScoredPoint objects with payload and score
    """
    dense_model = _resolve_dense_model_name(dense_model)
    weight = _resolve_dense_weight(query, dense_weight, keyword_boost_short_queries)

    db = _get_search_db(db, data_source)
    chunks_collection = db.chunks_collection

    dense_embedding_model = get_dense_model(dense_model)
    _ensure_embedding_server(dense_embedding_model)
    sparse_embedding_model = get_sparse_model()

    dense_vec, sparse_vec = _embed_query_vectors(
        query, dense_model, dense_embedding_model, sparse_embedding_model
    )

    query_filter = _build_query_filter(filters, section_types, data_source)
    fetch_limit = _compute_fetch_limit(limit, min_chunk_size)

    if weight >= 0.99:
        search_result = _run_dense_search(
            db,
            chunks_collection,
            dense_vec,
            dense_model,
            query_filter,
            fetch_limit,
            payload_fields,
        )
    elif weight <= 0.01:
        search_result = _run_sparse_search(
            db,
            chunks_collection,
            sparse_vec,
            query_filter,
            fetch_limit,
            payload_fields,
        )
    else:
        search_result = _run_hybrid_search(
            db,
            chunks_collection,
            dense_vec,
            sparse_vec,
            dense_model,
            query_filter,
            fetch_limit,
            payload_fields,
            weight,
            limit,
        )

    chunk_cache = None
    if (rerank or min_chunk_size > 0 or section_types) and isinstance(
        getattr(db, "pg", None), PostgresClient
    ):
        chunk_ids = [
            str(result.id) for result in search_result if result.id is not None
        ]
        if chunk_ids:
            t_chunk_cache_start = time.time()
            chunk_cache = db.pg.fetch_chunks(chunk_ids)
            t_chunk_cache_end = time.time()
            logger.info(
                "[TIMING] search_chunks chunk_cache_fetch: %.3fs (%s chunks)",
                t_chunk_cache_end - t_chunk_cache_start,
                len(chunk_cache),
            )
    if section_types:
        t_section_filter_start = time.time()
        search_result = _filter_section_types(
            search_result, section_types, chunk_cache=chunk_cache
        )
        t_section_filter_end = time.time()
        logger.info(
            "[TIMING] search_chunks section_filter: %.3fs (%s results)",
            t_section_filter_end - t_section_filter_start,
            len(search_result),
        )
    t_min_chunk_start = time.time()
    search_result = _filter_min_chunk_size(
        search_result, min_chunk_size, chunk_cache=chunk_cache
    )
    t_min_chunk_end = time.time()
    logger.info(
        "[TIMING] search_chunks min_chunk_filter: %.3fs (%s results)",
        t_min_chunk_end - t_min_chunk_start,
        len(search_result),
    )
    t_post_start = time.time()
    search_result = _apply_post_search_adjustments(
        search_result,
        query,
        limit,
        rerank,
        rerank_model,
        recency_boost,
        recency_weight,
        recency_scale_days,
        chunk_cache=chunk_cache,
    )
    t_post_end = time.time()
    logger.info(
        "[TIMING] search_chunks post_adjustments: %.3fs (%s results)",
        t_post_end - t_post_start,
        len(search_result),
    )
    return search_result


def scroll_filtered_chunks(
    filters: dict = None,
    limit: int = 50,
    data_source: str | None = None,
    section_types: List[str] = None,
) -> List[Any]:
    """Scroll chunks matching filters without a search query.

    Returns Qdrant points (with payload) so callers can count documents.
    """
    db = _get_search_db(None, data_source)
    query_filter = _build_query_filter(filters, section_types, data_source)
    points, _next_offset = db.client.scroll(
        collection_name=db.chunks_collection,
        scroll_filter=query_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    # Qdrant scroll returns Record (Pydantic) objects without a score field.
    # Wrap them so downstream code that expects .score works.
    from types import SimpleNamespace

    return [SimpleNamespace(id=p.id, payload=p.payload, score=0.0) for p in points]


def _collect_unique_doc_payloads(results: List[Any]) -> List[Dict[str, Any]]:
    seen_doc_ids = set()
    unique_docs = []
    for hit in results:
        doc_id = hit.payload.get("doc_id") or hit.payload.get("sys_doc_id")
        if doc_id and doc_id not in seen_doc_ids:
            seen_doc_ids.add(doc_id)
            unique_docs.append(hit.payload)
    return unique_docs


def _count_year_value(counter: Counter, val: Any) -> None:
    counter[str(val)] += 1


def _count_list_values(counter: Counter, val: List) -> None:
    for item in val:
        if item:
            counter[item] += 1


def _count_comma_separated(counter: Counter, val: str) -> None:
    for item in val.split(","):
        item = item.strip()
        if item:
            counter[item] += 1


def _accumulate_facet_counts(
    core_field: str,
    unique_docs: List[Dict[str, Any]],
    storage_field: Optional[str] = None,
) -> Counter:
    counter: Counter = Counter()
    storage_key = storage_field or map_field_to_storage(core_field)
    for doc_payload in unique_docs:
        val = doc_payload.get(storage_key)
        if not val:
            continue
        if core_field == "published_year":
            _count_year_value(counter, val)
        elif isinstance(val, list):
            _count_list_values(counter, val)
        elif (
            isinstance(val, str) and "," in val and core_field in ["country", "region"]
        ):
            _count_comma_separated(counter, val)
        else:
            counter[val] += 1
    return counter


def _format_facet_list(core_field: str, counter: Counter) -> List[Dict[str, Any]]:
    if core_field == "language":
        counter = Counter({LANGUAGE_NAMES.get(k, k): v for k, v in counter.items()})
    facets_list = [{"value": k, "count": v} for k, v in counter.most_common()]
    if core_field == "published_year":
        facets_list.sort(key=lambda x: x["value"], reverse=True)
    return facets_list


def get_search_facets(
    query: str,
    filters: dict = None,
    limit: int = 2000,
    dense_weight: float = None,
    data_source: str = None,
) -> Dict[str, List[Any]]:
    """
    Get facet counts based on a search query.
    Performs a high-limit search and aggregates metadata fields.

    Args:
        query: Search query
        filters: Current active filters
        limit: Number of results to analyze for faceting (default 2000)
    """

    source = data_source or "uneg"
    db = _get_search_db(None, source)
    filter_fields_config = get_filter_fields(source)
    from pipeline.db import get_taxonomy_filter_fields  # noqa: PLC0415

    filter_fields_config = {
        **filter_fields_config,
        **get_taxonomy_filter_fields(source),
    }

    # 1. Determine which fields we need to fetch
    needed_fields = ["doc_id", "sys_doc_id"]  # Include sys_doc_id for deduplication
    for core_field in filter_fields_config.keys():
        needed_fields.append(_resolve_storage_field(core_field, source))

    # Always fetching title for reference if needed, but not for faceting if too high cardinality
    # needed_fields.append("title")

    # 2. Perform search with optimized payload
    # We disable expensive steps like reranking and recency boost for pure faceting speed
    # Reduced limit from 2000 to 500 to significantly improve performance (17s -> ~2s)
    # 500 results is usually sufficient for a representative facet distribution
    results = search_chunks(
        query=query,
        limit=500,
        dense_weight=dense_weight,
        data_source=source,
        filters=filters,
        rerank=False,
        recency_boost=False,
        payload_fields=needed_fields,
    )

    # 3. Aggregate results
    facets_data = {}

    # We use a set of seen doc_ids to avoid double counting chunks from same doc?
    # No, usually facets in search results represent "Matching Items".
    # If the user searches "water", and a document has 5 chunks about water,
    # should it count as 1 or 5?
    # Standard eCommerce/Search usually counts DOCUMENTS.
    # Qdrant returns CHUNKS.
    # We should deduplicate by doc_id to get Document counts.

    unique_docs = _collect_unique_doc_payloads(results)
    doc_ids = [
        doc.get("doc_id") or doc.get("sys_doc_id")
        for doc in unique_docs
        if doc.get("doc_id") or doc.get("sys_doc_id")
    ]

    for core_field in filter_fields_config.keys():
        if core_field == "title":
            # Skip title faceting as it's too high cardinality
            pass
        storage_field = _resolve_storage_field(core_field, source)
        if storage_field == "sys_language" and isinstance(
            getattr(db, "pg", None), PostgresClient
        ):
            if doc_ids:
                placeholders = ", ".join(["%s"] * len(doc_ids))
                sql = f"""
                    SELECT sys_language
                    FROM {db.pg.docs_table}
                    WHERE doc_id IN ({placeholders})
                """
                with db.pg._get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, doc_ids)
                        rows = cur.fetchall()
                counter = Counter(row[0] for row in rows if row[0] not in (None, ""))
            else:
                counter = Counter()
        else:
            counter = _accumulate_facet_counts(
                core_field, unique_docs, storage_field=storage_field
            )
        facets_data[core_field] = _format_facet_list(core_field, counter)

    return facets_data


# CLI interface needs update too if used
def search(
    query: str, limit: int = 10, dense_weight: float = 0.8, dense_model: str = None
):
    """
    Search the index for the query.
    CLI interface for semantic search.
    """
    t_start = time.time()

    # Pre-load models (so timing doesn't include model loading)
    get_models(dense_model)

    # Search using shared function
    t0 = time.time()
    search_result = search_chunks(
        query, limit, dense_weight=dense_weight, dense_model=dense_model
    )
    t1 = time.time()

    # Aggregate results by Document
    logger.info(f"Found {len(search_result)} hits in {t1-t0:.3f}s")
    if dense_model:
        logger.info(f"Used model: {dense_model}")

    # Fetch metadata for all results
    t2 = time.time()
    for hit in search_result:
        payload = hit.payload
        doc_id = payload.get("doc_id")

        # Fetch Document Metadata
        pg = PostgresClient()
        doc_meta_map = pg.fetch_docs([doc_id])
        doc_meta = doc_meta_map.get(str(doc_id))

        print(f"\n--- Score: {hit.score:.4f} ---")
        print(
            f"Document: {doc_meta.get('map_title', 'Unknown') if doc_meta else 'Unknown'} "
            f"({doc_meta.get('map_organization', 'Unknown') if doc_meta else 'Unknown'}, "
            f"{doc_meta.get('map_published_year', 'Unknown') if doc_meta else 'Unknown'})"
        )
        print(f"Page: {payload.get('page_num')}")
        print(f"Snippet: {payload.get('text', '')[:200]}...")
        print("-" * 30)

    t3 = time.time()

    # Summary timing
    print("\n{'='*60}")
    print("SEARCH TIMING SUMMARY")
    print(f"{'='*60}")
    # Defines search_mode for print
    search_mode = (
        "Hybrid"
        if 0.01 < dense_weight < 0.99
        else ("Dense" if dense_weight >= 0.99 else "Sparse")
    )
    print(f"Search mode:         {search_mode} (weight={dense_weight:.2f})")
    print(f"Model:               {dense_model or 'Default'}")
    print(f"Query execution:     {t1-t0:.3f}s")
    print(f"Metadata fetch:      {t3-t2:.3f}s")
    print(f"Total time:          {t3-t_start:.3f}s")
    print(f"Results returned:    {len(search_result)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Search the humanitarian evaluation index."
    )
    parser.add_argument("query", type=str, help="The search query")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of results to return"
    )
    parser.add_argument(
        "--dense-weight",
        type=float,
        default=0.8,
        help="Weight for dense (semantic) search in hybrid mode (0.0=keyword, 1.0=semantic, default=0.8)",  # noqa: E501
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Name of dense model to use (default: env configured)",
    )

    args = parser.parse_args()
    search(args.query, args.limit, args.dense_weight, args.model)


def _build_document_filter(
    filters: Optional[dict], data_source: Optional[str]
) -> Optional[models.Filter]:
    must_conditions: List[models.Condition] = []
    filters = map_filters_to_storage(filters, data_source=data_source)
    if filters:
        for field, value in filters.items():
            if not value or field in {"title", "map_title"}:
                continue
            must_conditions.append(
                models.FieldCondition(key=field, match=models.MatchValue(value=value))
            )
    return models.Filter(must=must_conditions) if must_conditions else None


def _extract_title_keywords(query: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", (query or "").lower())
    return list(dict.fromkeys(token for token in tokens if token))


def _build_title_keyword_filter(
    filters: Optional[dict], data_source: Optional[str], keywords: List[str]
) -> Optional[models.Filter]:
    base_filter = _build_document_filter(filters, data_source)
    must_conditions = list(base_filter.must or []) if base_filter else []
    for token in keywords:
        must_conditions.append(
            models.FieldCondition(key="map_title", match=models.MatchText(text=token))
        )
    if not must_conditions:
        return None
    return models.Filter(
        must=must_conditions or None,
    )


def _score_title_keywords(title: str, keywords: List[str]) -> int:
    lowered_title = title.lower()
    return sum(1 for token in keywords if token in lowered_title)


def _scroll_title_batch(
    db: Database,
    collection_name: str,
    query_filter: Optional[models.Filter],
    fetch_limit: int,
    offset: Optional[int],
):
    scroll_kwargs = {
        "collection_name": collection_name,
        "limit": fetch_limit,
        "with_payload": True,
    }
    if query_filter is not None:
        scroll_kwargs["scroll_filter"] = query_filter
    if offset is not None:
        scroll_kwargs["offset"] = offset

    scroll_response = db.client.scroll(**scroll_kwargs)
    if isinstance(scroll_response, tuple):
        points, next_offset = scroll_response
    else:
        points = getattr(scroll_response, "points", scroll_response)
        next_offset = getattr(scroll_response, "next_page_offset", None)
    return points, next_offset


def _collect_title_keyword_matches(points: List[Any], keywords: List[str]):
    matches = []
    for point in points:
        payload = point.payload or {}
        title = str(payload.get("map_title") or "")
        score = _score_title_keywords(title, keywords)
        if score <= 0:
            continue
        if "doc_id" not in payload and getattr(point, "id", None) is not None:
            payload = dict(payload)
            payload["doc_id"] = point.id
        matches.append(SimpleNamespace(payload=payload, score=float(score)))
    return matches


def _run_title_keyword_search(
    db: Database,
    collection_name: str,
    keywords: List[str],
    query_filter: Optional[models.Filter],
    limit: int,
):
    if not keywords:
        return []
    fetch_limit = min(max(limit * 5, limit), 200)
    max_scanned = max(limit * 60, 3000)
    scanned = 0
    offset: Optional[int] = None
    results: List[SimpleNamespace] = []

    while scanned < max_scanned and len(results) < limit:
        points, offset = _scroll_title_batch(
            db, collection_name, query_filter, fetch_limit, offset
        )

        if not points:
            break

        scanned += len(points)
        results.extend(_collect_title_keyword_matches(points, keywords))

        if offset is None:
            break

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]


def _run_title_dense_search(
    db: Database,
    collection_name: str,
    dense_vec,
    dense_model: str,
    query_filter: Optional[models.Filter],
    limit: int,
):
    query_response = db.client.query_points(
        collection_name=collection_name,
        query=dense_vec.tolist(),
        using=dense_model,
        query_filter=query_filter,
        limit=limit,
        search_params=models.SearchParams(hnsw_ef=SEARCH_HNSW_EF, exact=SEARCH_EXACT),
        with_payload=True,
    )
    return query_response.points


def _run_title_sparse_search(
    db: Database,
    collection_name: str,
    sparse_vec,
    query_filter: Optional[models.Filter],
    limit: int,
):
    query_response = db.client.query_points(
        collection_name=collection_name,
        query=models.SparseVector(
            indices=sparse_vec.indices.tolist(), values=sparse_vec.values.tolist()
        ),
        using=SPARSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    return query_response.points


def search_titles(
    query: str,
    limit: int = 50,
    dense_weight: float = None,
    db: Database = None,
    filters: dict = None,
    dense_model: str = None,
) -> List[Any]:
    """
    Hybrid search specifically for document TITLES/Metadata using the 'documents' collection.

    Args:
        query: Search query string
        limit: Maximum results to return
        dense_weight: Optional weight for dense search. If None, uses SEARCH_DENSE_WEIGHT.
        db: Database instance.
        filters: Filters to apply.
        dense_model: Embedding model to use.

    Returns:
        List of Qdrant ScoredPoint objects representing Documents (not chunks).
    """
    if db is None:
        db = get_db()

    collection_name = db.documents_collection
    keywords = _extract_title_keywords(query)
    query_filter = _build_title_keyword_filter(
        filters, db.data_source if db else None, keywords
    )
    return _run_title_keyword_search(db, collection_name, keywords, query_filter, limit)


def search_facet_values(
    field: str,
    query: str,
    limit: int = 100,
    dense_weight: Optional[float] = None,
    db: Optional[Database] = None,
    dense_model: str = DENSE_VECTOR_NAME,
    data_source: str = "uneg",
) -> List[Dict[str, Any]]:
    """
    Search for unique values of a specific field by querying the documents collection.

    Args:
        field: The field to aggregate (e.g. 'organization', 'year')
        query: Search query string
        limit: Number of documents to fetch (to find values)
        ...

    Returns:
        List of dicts with 'value' and 'count', sorted by count desc.
    """
    target_field = _resolve_storage_field(field, data_source)
    if not target_field.startswith(("map_", "sys_", "src_")):
        return []

    query_value = (query or "").strip()

    if target_field.startswith(("map_", "sys_", "src_")):
        db = db or get_db(data_source)
        try:
            result = db.client.facet(
                collection_name=db.documents_collection,
                key=target_field,
                limit=limit,
                exact=False,
            )
        except Exception:
            return []

        if isinstance(result, dict):
            hits = result.get("hits", [])
        else:
            hits = result.hits

        facets_list = [
            {"value": str(hit.value), "count": hit.count}
            for hit in hits
            if hit.value not in (None, "")
        ]
        if not query_value:
            return facets_list

        lowered_query = query_value.lower()
        return [
            facet
            for facet in facets_list
            if lowered_query in str(facet["value"]).lower()
        ]

    db = db or get_db(data_source)
    pg = getattr(db, "pg", None)
    if not pg:
        return []

    params: List[object] = []
    where_clause = ""
    if query_value:
        where_clause = f"WHERE {target_field} ILIKE %s"
        params.append(f"%{query_value}%")
    params.append(limit)

    sql = f"""
        SELECT {target_field}, COUNT(*)
        FROM {pg.docs_table}
        {where_clause}
        GROUP BY {target_field}
        ORDER BY COUNT(*) DESC
        LIMIT %s
    """

    rows: List[tuple] = []
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        {"value": str(value), "count": count}
        for value, count in rows
        if value not in (None, "")
    ]
