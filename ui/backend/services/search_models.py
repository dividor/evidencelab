import importlib
import json
import logging
import math
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from pipeline.db import (  # noqa: E402
    DB_VECTORS,
    DENSE_VECTOR_NAME,
    SUPPORTED_RERANK_MODELS,
    get_application_config,
)
from pipeline.utilities.azure_client import AzureEmbeddingClient  # noqa: E402
from pipeline.utilities.embedding_client import RemoteEmbeddingClient  # noqa: E402

load_dotenv()

logger = logging.getLogger(__name__)

# Load search configuration
app_config = get_application_config()
search_config = app_config.get("search", {})

# Load search configuration from environment - MUST be set in .env
DENSE_MODEL = DENSE_VECTOR_NAME
SPARSE_MODEL = "Qdrant/bm25"  # TODO: Load from config if needed, or keep constant
USE_EMBEDDING_SERVER = os.getenv("USE_EMBEDDING_SERVER", "false").lower() in (
    "1",
    "true",
    "yes",
)
EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL")
MAX_DOC_ID_FILTER = int(os.getenv("SEARCH_DOC_ID_FILTER_LIMIT", "10000"))

_resolved_embedding_api_url: Optional[str] = None

# Rerank model key from config, fallback to default
RERANK_MODEL = search_config.get(
    "rerank_model", "jinaai/jina-reranker-v2-base-multilingual"
)
SEARCH_DENSE_WEIGHT = float(search_config.get("dense_weight", 1.0))

# E5 models require special prefixes for queries and passages
IS_E5_MODEL = "e5" in DENSE_MODEL.lower()

SEARCH_HNSW_EF = int(os.getenv("SEARCH_HNSW_EF", search_config.get("hnsw_ef", 128)))
SEARCH_EXACT = os.getenv(
    "SEARCH_EXACT", str(search_config.get("exact", False))
).lower() in ("1", "true", "yes")
QUANTIZATION_RESCORE = os.getenv(
    "QUANTIZATION_RESCORE", str(search_config.get("quantization_rescore", True))
).lower() in ("1", "true", "yes")
SEARCH_FETCH_LIMIT = int(os.getenv("SEARCH_FETCH_LIMIT", "50"))

# Cache models for reuse
_dense_models_cache: dict[str, Any] = {}
_dense_models_lock = threading.Lock()
_sparse_model = None
_sparse_model_lock = threading.Lock()
_rerank_models_cache: dict[str, Any] = {}
_rerank_models_lock = threading.Lock()
MAX_CONCURRENT_RERANKS = int(os.environ.get("MAX_CONCURRENT_RERANKS", "1"))
_rerank_semaphore = threading.Semaphore(MAX_CONCURRENT_RERANKS)


def _normalize_embedding_url(url: str) -> str:
    if "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/")


def _embedding_server_healthy(base_url: str) -> bool:
    health_paths = ("/health", "/")
    for path in health_paths:
        try:
            request = Request(f"{base_url}{path}", method="GET")
            with urlopen(request, timeout=1) as response:
                if 200 <= response.status < 300:
                    return True
        except Exception:
            continue
    return False


def _reset_cached_embedding_url(env_url: Optional[str]) -> None:
    global _resolved_embedding_api_url
    if not env_url:
        return
    parsed_env_url = urlparse(_normalize_embedding_url(env_url))
    if parsed_env_url.hostname == "embedding-server":
        _resolved_embedding_api_url = None


def _build_embedding_candidates(
    env_url: Optional[str],
) -> tuple[List[str], Optional[str]]:
    candidates: List[str] = []
    port = 7997
    normalized_env_url = None

    if env_url:
        normalized_env_url = _normalize_embedding_url(env_url)
        candidates.append(normalized_env_url)
        parsed_env_url = urlparse(normalized_env_url)
        if parsed_env_url.port:
            port = parsed_env_url.port
        if parsed_env_url.hostname == "embedding-server":
            logger.warning(
                "Embedding server URL points to docker host %s; enabling host fallbacks.",
                normalized_env_url,
            )

    host_fallbacks = [
        f"http://host.docker.internal:{port}",
        f"http://localhost:{port}",
    ]
    for fallback in host_fallbacks:
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates, normalized_env_url


def get_embedding_api_url() -> str:
    global _resolved_embedding_api_url

    env_url = EMBEDDING_API_URL
    _reset_cached_embedding_url(env_url)

    if _resolved_embedding_api_url:
        if _embedding_server_healthy(_resolved_embedding_api_url):
            return _resolved_embedding_api_url
        logger.warning(
            "Cached embedding server URL %s is not reachable; re-resolving.",
            _resolved_embedding_api_url,
        )
        _resolved_embedding_api_url = None

    candidates, normalized_env_url = _build_embedding_candidates(env_url)

    for candidate in candidates:
        if _embedding_server_healthy(candidate):
            _resolved_embedding_api_url = candidate
            if env_url and normalized_env_url and candidate != normalized_env_url:
                logger.warning(
                    "Embedding server at %s not reachable; falling back to %s",
                    normalized_env_url,
                    candidate,
                )
            elif not env_url:
                logger.info(
                    "Embedding server URL not set; using local server at %s",
                    candidate,
                )
            return candidate

    if env_url:
        raise RuntimeError(
            "Embedding server not reachable at any configured URL. "
            f"Tried: {', '.join(candidates)}"
        )
    raise RuntimeError(
        "EMBEDDING_API_URL must be set or a local embedding server must be running."
    )


def add_query_prefix(text: str, model_name: str = "") -> str:
    """Add 'query: ' prefix for E5 models during search."""
    # Check if 'e5' is in the model name (case insensitive)
    if "e5" in model_name.lower():
        return f"query: {text}"
    return text


def _resolve_vector_name(
    vector_name: Optional[str],
    db_vectors: Optional[Dict[str, Any]] = None,
    dense_model: Optional[str] = None,
) -> str:
    resolved_name = vector_name or dense_model or DENSE_MODEL
    vectors = db_vectors or DB_VECTORS
    if resolved_name not in vectors:
        raise ValueError(f"Unknown vector name: {resolved_name}")
    if not vectors[resolved_name].get("enabled", True):
        raise ValueError(f"Vector name disabled: {resolved_name}")
    return resolved_name


def _validate_vector_name(
    vector_name: str, db_vectors: Optional[Dict[str, Any]] = None
) -> None:
    vectors = db_vectors or DB_VECTORS
    if vector_name not in vectors:
        raise ValueError(f"Unknown vector name: {vector_name}")
    if not vectors[vector_name].get("enabled", True):
        raise ValueError(f"Vector name disabled: {vector_name}")


def _refresh_embedding_server_base_url(model: Any) -> None:
    if not hasattr(model, "base_url"):
        return
    model.base_url = get_embedding_api_url()


def _get_cached_dense_model(vector_name: str) -> Any:
    return _dense_models_cache.get(vector_name)


def _init_dense_model(vector_name: str, vec_config: Dict[str, Any]) -> Any:
    model_id = vec_config.get("model_id")
    if not model_id:
        raise ValueError(f"Missing model_id for {vector_name}")

    source = vec_config.get("source", "huggingface")
    if source == "azure_foundry":
        api_key = os.getenv("AZURE_FOUNDRY_KEY")
        endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
        if not api_key or not endpoint:
            raise ValueError(
                "AZURE_FOUNDRY_KEY and AZURE_FOUNDRY_ENDPOINT are required."
            )
        return AzureEmbeddingClient(
            api_key=api_key,
            endpoint=endpoint,
            deployment_name=str(model_id),
        )

    if USE_EMBEDDING_SERVER:
        if source not in {"huggingface", "fastembed"}:
            raise ValueError(
                f"Embedding server does not support source '{source}' for {vector_name}"
            )
        client = RemoteEmbeddingClient(
            base_url=get_embedding_api_url(),
            model_name=model_id,
        )
        _refresh_embedding_server_base_url(client)
        return client

    fastembed = importlib.import_module("fastembed")
    return fastembed.TextEmbedding(model_id)


def get_dense_model(
    vector_name: str = None,
    *,
    db_vectors: Optional[Dict[str, Any]] = None,
    cache: Optional[Dict[str, Any]] = None,
    lock: Optional[threading.Lock] = None,
    dense_model: Optional[str] = None,
):
    resolved = _resolve_vector_name(
        vector_name, db_vectors=db_vectors, dense_model=dense_model
    )
    vectors = db_vectors or DB_VECTORS
    cache = cache if cache is not None else _dense_models_cache
    lock = lock if lock is not None else _dense_models_lock
    cached = cache.get(resolved)
    if cached is not None:
        return cached
    with lock:
        cached = cache.get(resolved)
        if cached is not None:
            return cached
        vec_config = vectors[resolved]
        model = _init_dense_model(resolved, vec_config)
        cache[resolved] = model
        return model


def get_sparse_model(
    *,
    model_name: Optional[str] = None,
    cache: Optional[Any] = None,
    lock: Optional[threading.Lock] = None,
):
    model_name = model_name or SPARSE_MODEL
    cache = cache if cache is not None else _sparse_model
    lock = lock if lock is not None else _sparse_model_lock
    if cache is not None:
        return cache
    with lock:
        if _sparse_model is not None:
            return _sparse_model
        fastembed = importlib.import_module("fastembed")
        sparse_model = fastembed.SparseTextEmbedding(model_name)
        globals()["_sparse_model"] = sparse_model
        return sparse_model


def get_models(
    dense_vector_name: str = None,
    *,
    db_vectors: Optional[Dict[str, Any]] = None,
    dense_cache: Optional[Dict[str, Any]] = None,
    dense_lock: Optional[threading.Lock] = None,
    sparse_cache: Optional[Any] = None,
    sparse_lock: Optional[threading.Lock] = None,
    dense_model: Optional[str] = None,
):
    dense_model_instance = get_dense_model(
        dense_vector_name,
        db_vectors=db_vectors,
        cache=dense_cache,
        lock=dense_lock,
        dense_model=dense_model,
    )
    sparse_model_instance = get_sparse_model(
        cache=sparse_cache, lock=sparse_lock, model_name=SPARSE_MODEL
    )
    return dense_model_instance, sparse_model_instance


def _resolve_rerank_model_name(
    model_key: Optional[str], rerank_model: Optional[str] = None
) -> str:
    if model_key:
        return model_key
    return rerank_model or RERANK_MODEL


def _get_rerank_model_config(
    model_key: Optional[str],
    supported_rerank_models: Optional[Dict[str, Any]] = None,
    rerank_model: Optional[str] = None,
) -> Dict[str, Any]:
    model_name = _resolve_rerank_model_name(model_key, rerank_model=rerank_model)
    supported = supported_rerank_models or SUPPORTED_RERANK_MODELS
    if model_name in supported:
        return supported[model_name]
    normalized = model_name.lower()
    for key, config in supported.items():
        if key.lower() == normalized:
            return config
        model_id = str(config.get("model_id", "")).lower()
        if model_id == normalized:
            return config
    return {}


def _is_azure_foundry_reranker(config: Dict[str, Any]) -> bool:
    return (
        config.get("provider") == "azure_foundry"
        or config.get("source") == "azure_foundry"
    )


def _get_azure_foundry_rerank_endpoint(config: Dict[str, Any], deployment: str) -> str:
    endpoint = (
        config.get("endpoint_url")
        or config.get("endpoint")
        or os.getenv("AZURE_FOUNDRY_ENDPOINT")
    )
    if not endpoint:
        raise ValueError("Azure Foundry rerank endpoint not configured.")
    azure_base = endpoint.rstrip("/")
    if "/providers/cohere/" in azure_base:
        return azure_base
    if "/openai/deployments/" in azure_base:
        azure_base = azure_base.split("/openai/deployments/")[0]
    if azure_base.endswith(".openai.azure.com"):
        azure_base = azure_base.replace(".openai.azure.com", ".services.ai.azure.com")
    return f"{azure_base}/providers/cohere/v2/rerank"


def _get_azure_foundry_api_key() -> str:
    api_key = os.getenv("AZURE_FOUNDRY_KEY")
    if not api_key:
        raise ValueError("AZURE_FOUNDRY_KEY is required for Azure Foundry reranking.")
    return api_key


def _scores_from_results(results: Any, doc_count: int) -> Optional[List[float]]:
    if not results:
        return None
    # Check if results include an "index" field (e.g. Cohere rerank API returns
    # results sorted by relevance, with "index" mapping back to original doc order).
    has_index = all(isinstance(r, dict) and "index" in r for r in results)
    if has_index:
        scores: List[Optional[float]] = [None] * doc_count
        for result in results:
            idx = result["index"]
            score = (
                result.get("relevance_score")
                or result.get("score")
                or result.get("relevanceScore")
            )
            if score is None or not isinstance(idx, int) or idx < 0 or idx >= doc_count:
                return None
            scores[idx] = score
        if any(s is None for s in scores):
            return None
        return [float(s) for s in scores]  # type: ignore[arg-type]
    # Fallback: scores in iteration order (no index field)
    scores_list = []
    for result in results:
        score = result.get("score")
        if score is None:
            score = result.get("relevance_score")
        if score is None:
            score = result.get("relevanceScore")
        if score is None:
            return None
        scores_list.append(score)
    if len(scores_list) != doc_count:
        return None
    return scores_list


def _scores_from_list(scores: Any) -> Optional[List[float]]:
    if not isinstance(scores, list):
        return None
    if not all(isinstance(score, (float, int)) for score in scores):
        return None
    return [float(score) for score in scores]


def _scores_from_data(data: Any, doc_count: int) -> Optional[List[float]]:
    if not isinstance(data, dict):
        return None
    scores = data.get("scores") or data.get("results") or data.get("data")
    if scores is None:
        return None
    if isinstance(scores, list) and all(isinstance(item, dict) for item in scores):
        return _scores_from_results(scores, doc_count)
    if isinstance(scores, list):
        parsed_scores = _scores_from_list(scores)
        if parsed_scores and len(parsed_scores) == doc_count:
            return parsed_scores
    return None


def _parse_azure_rerank_response(response_text: Any, doc_count: int) -> List[float]:
    if isinstance(response_text, str):
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError("Azure rerank response is not valid JSON.")
    else:
        data = response_text

    scores = _scores_from_data(data, doc_count)
    if scores is None:
        raise ValueError("Azure rerank response missing scores.")
    return scores


def _rerank_with_azure_foundry(
    query: str, documents: List[str], deployment: str, config: Dict[str, Any]
) -> List[float]:
    payload = {
        "model": deployment,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
    }
    endpoint = _get_azure_foundry_rerank_endpoint(config, deployment)
    api_key = _get_azure_foundry_api_key()
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        response_text = response.read().decode("utf-8")
    return _parse_azure_rerank_response(response_text, len(documents))


def get_rerank_model(
    model_key: Optional[str] = None,
    *,
    supported_rerank_models: Optional[Dict[str, Any]] = None,
    cache: Optional[Dict[str, Any]] = None,
    lock: Optional[threading.Lock] = None,
    rerank_model: Optional[str] = None,
):
    model_name = _resolve_rerank_model_name(model_key, rerank_model=rerank_model)
    supported = supported_rerank_models or SUPPORTED_RERANK_MODELS
    cache = cache if cache is not None else _rerank_models_cache
    lock = lock if lock is not None else _rerank_models_lock
    cached = cache.get(model_name)
    if cached is not None:
        return cached

    with lock:
        cached = cache.get(model_name)
        if cached is not None:
            return cached

        rerank_config = _get_rerank_model_config(
            model_name, supported_rerank_models=supported, rerank_model=rerank_model
        )
        if supported and model_name not in supported:
            raise ValueError(f"Unknown rerank model: {model_name}")
        if _is_azure_foundry_reranker(rerank_config):
            model = {"type": "azure_foundry", "config": rerank_config}
        else:
            cross_encoder_module = importlib.import_module(
                "fastembed.rerank.cross_encoder"
            )
            model_id = rerank_config.get("model_id", model_name)
            model = cross_encoder_module.TextCrossEncoder(model_name=model_id)

        cache[model_name] = model
        return model


def rerank_results(
    query: str,
    results: List[Any],
    rerank_model: Optional[str] = None,
    limit: Optional[int] = None,
    chunk_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    max_rerank_candidates: int = 0,
    supported_rerank_models: Optional[Dict[str, Any]] = None,
    rerank_model_loader: Optional[Any] = None,
) -> List[Any]:
    if not results:
        return results

    t_rerank_start = time.time()
    if max_rerank_candidates <= 0:
        max_rerank_candidates = len(results)
    candidates_to_rerank = results[:max_rerank_candidates]
    remaining_results = results[max_rerank_candidates:]

    # Extract text for reranking
    t_rerank_prepare_start = time.time()
    documents = []
    for result in candidates_to_rerank:
        chunk_payload = (
            chunk_cache.get(str(result.id))
            if chunk_cache and result.id is not None
            else None
        )
        chunk_text = (
            chunk_payload.get("sys_text")
            if chunk_payload and chunk_payload.get("sys_text")
            else result.payload.get("text")
        )
        if chunk_text:
            documents.append(chunk_text)
        else:
            documents.append("")
    t_rerank_prepare_end = time.time()
    logger.info(
        "[TIMING] rerank prepare_docs: %.3fs (%s docs)",
        t_rerank_prepare_end - t_rerank_prepare_start,
        len(documents),
    )

    model_name = _resolve_rerank_model_name(rerank_model)
    logger.info(
        "Reranking %s results with %s (max_concurrent=%s)...",
        len(documents),
        model_name,
        MAX_CONCURRENT_RERANKS,
    )
    rerank_config = _get_rerank_model_config(
        rerank_model, supported_rerank_models=supported_rerank_models
    )
    t_rerank_infer_start = time.time()
    if _is_azure_foundry_reranker(rerank_config):
        deployment = rerank_config.get("model_id", model_name)
        with _rerank_semaphore:
            rerank_scores = _rerank_with_azure_foundry(
                query=query,
                documents=documents,
                deployment=deployment,
                config=rerank_config,
            )
    else:
        if rerank_model_loader is not None:
            reranker = rerank_model_loader(rerank_model)
        else:
            reranker = get_rerank_model(
                rerank_model, supported_rerank_models=supported_rerank_models
            )
        with _rerank_semaphore:
            rerank_scores = list(reranker.rerank(query, documents))
    t_rerank_infer_end = time.time()
    logger.info(
        "[TIMING] rerank inference: %.3fs (%s docs)",
        t_rerank_infer_end - t_rerank_infer_start,
        len(documents),
    )

    # Combine results with rerank scores (rerank returns raw float scores)
    results_with_scores = list(zip(candidates_to_rerank, rerank_scores))

    # Sort by rerank score (descending)
    results_with_scores.sort(key=lambda x: x[1], reverse=True)

    # Update scores and return
    reranked_results = []
    for result, rerank_score in results_with_scores:
        # Update the score to reflect the rerank score
        result.score = rerank_score
        reranked_results.append(result)

    # Add remaining results (not reranked) at the end
    reranked_results.extend(remaining_results)

    # Apply limit if specified
    if limit is not None:
        reranked_results = reranked_results[:limit]

    t_rerank_end = time.time()
    logger.info(
        "[TIMING] rerank total: %.3fs (%s results)",
        t_rerank_end - t_rerank_start,
        len(reranked_results),
    )
    logger.info(f"✓ Reranking complete, returning {len(reranked_results)} results")
    return reranked_results


def apply_recency_boost(
    results: List[Any],
    recency_weight: float = 0.15,
    scale_days: int = 365,
) -> List[Any]:
    """
    Apply recency boosting to search results based on publication date.

    Uses Gaussian decay function where:
    - Documents from this year (or last year) get maximum boost (1.0)
    - Older documents decay exponentially based on scale_days

    The decay is calculated from the *end* of the publication year, so:
    - 2025 reports: full boost (current year)
    - 2024 reports: full boost (less than 1 year old)
    - 2023 reports: partial boost (decaying based on scale)

    The final score is: (1 - recency_weight) * original_score + recency_weight * recency_factor

    Args:
        results: List of Qdrant ScoredPoint objects
        recency_weight: How much to weight recency vs relevance (0.0-1.0).
                        Default 0.15 = 15% recency, 85% relevance
        scale_days: Days for decay to reach ~37% of max boost.
                    Default 365 = 1 year scale (so reports 1+ years old start decaying)

    Returns:
        Reordered list with adjusted scores
    """
    if not results:
        return results

    # Use current date as reference point
    now = datetime.now()
    now_unix = int(now.timestamp())
    scale_seconds = scale_days * 24 * 60 * 60

    # Calculate recency-adjusted scores
    scored_results = []
    for result in results:
        original_score = result.score
        published_unix = result.payload.get("published_date_unix")

        if published_unix is None:
            # No publication date - use original score with no recency boost
            recency_factor = 0.5  # Neutral factor for missing dates
        else:
            # Calculate age from end of publication year (Dec 31)
            # This ensures current year and last year reports get high boost
            pub_year = datetime.fromtimestamp(published_unix).year
            pub_year_end_unix = int(datetime(pub_year, 12, 31).timestamp())

            # Age is from the end of publication year to now
            age_seconds = max(0, now_unix - pub_year_end_unix)

            # Gaussian decay: exp(-0.5 * (age / scale)^2)
            # This gives ~1.0 for recent reports, decaying for older years
            recency_factor = math.exp(-0.5 * (age_seconds / scale_seconds) ** 2)

        # Combine original score with recency factor
        # Normalize recency_factor to similar scale as score (scores are typically 0-1)
        adjusted_score = (
            1 - recency_weight
        ) * original_score + recency_weight * recency_factor

        scored_results.append((result, adjusted_score, original_score, recency_factor))

    # Sort by adjusted score (descending)
    scored_results.sort(key=lambda x: x[1], reverse=True)

    # Update scores and return
    reordered_results = []
    for result, adjusted_score, original_score, recency_factor in scored_results:
        result.score = adjusted_score
        # Store original score and recency factor in payload for transparency
        result.payload["_original_score"] = original_score
        result.payload["_recency_factor"] = recency_factor
        reordered_results.append(result)

    logger.info(
        f"✓ Applied recency boost (weight={recency_weight}, scale={scale_days}d) "
        f"to {len(results)} results"
    )
    return reordered_results
