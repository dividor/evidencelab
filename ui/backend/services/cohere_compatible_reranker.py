"""Reranker for any Cohere-compatible ``/rerank`` endpoint.

Works with Cohere itself and with providers that expose the same API
(``POST {base_url}/rerank`` with ``model``, ``query``, ``documents`` and a
``results`` list of ``{"index", "relevance_score"}`` in the response).

Model config (``supported_rerank_models``)::

    "my_reranker": {
        "model_id": "provider/model-name",
        "provider": "cohere_compatible",
        "base_url_env": "COHERE_BASE_URL",   # optional, this is the default
        "api_key_env": "COHERE_API_KEY",  # optional  # pragma: allowlist secret
        "endpoint_url": "https://...",       # optional, overrides base_url_env
        "timeout": 30                        # optional, seconds
    }
"""

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ui.backend.services.google_vertex_reranker import RerankerUnavailableError

DEFAULT_BASE_URL_ENV = "COHERE_BASE_URL"
DEFAULT_API_KEY_ENV = "COHERE_API_KEY"  # pragma: allowlist secret
DEFAULT_TIMEOUT_SECONDS = 30


def _get_endpoint(config: Dict[str, Any]) -> str:
    """Resolve the rerank URL; ``/rerank`` is appended if missing."""
    base_url_env = config.get("base_url_env", DEFAULT_BASE_URL_ENV)
    endpoint = config.get("endpoint_url") or os.getenv(base_url_env)
    if not endpoint:
        raise ValueError(
            f"Rerank endpoint not configured: set {base_url_env} "
            "(or 'endpoint_url' in the rerank model config)."
        )
    if not endpoint.startswith("https://"):
        raise ValueError(f"Rerank endpoint must use HTTPS, got: {endpoint!r}")
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/rerank"):
        endpoint += "/rerank"
    return endpoint


def _get_api_key(config: Dict[str, Any]) -> str:
    api_key_env = config.get("api_key_env", DEFAULT_API_KEY_ENV)
    key = os.getenv(api_key_env)
    if not key:
        raise ValueError(f"{api_key_env} is required for reranking.")
    return key


def parse_rerank_response(data: Any, doc_count: int) -> List[float]:
    """Return scores in the original document order."""
    results: Optional[Any] = None
    if isinstance(data, dict):
        results = data.get("results") or data.get("data") or data.get("scores")
    if not isinstance(results, list) or not results:
        raise ValueError("Rerank response missing results.")
    if all(isinstance(r, (int, float)) for r in results):
        if len(results) != doc_count:
            raise ValueError("Rerank returned the wrong number of scores.")
        return [float(r) for r in results]

    scores: List[Optional[float]] = [None] * doc_count
    for pos, item in enumerate(results):
        if not isinstance(item, dict):
            raise ValueError("Rerank response has invalid entries.")
        idx = item.get("index", pos)
        score = item.get("relevance_score")
        if score is None:
            score = item.get("score")
        if not isinstance(idx, int) or not 0 <= idx < doc_count or score is None:
            raise ValueError("Rerank response has invalid entries.")
        scores[idx] = float(score)

    # Documents the API chose not to return rank below every returned one.
    returned = [s for s in scores if s is not None]
    floor = min(returned) - 1.0
    return [s if s is not None else floor for s in scores]


def rerank_with_cohere_compatible(
    query: str,
    documents: List[str],
    model_id: str,
    config: Dict[str, Any],
) -> List[float]:
    """Rerank via a Cohere-compatible API.

    Raises ``RerankerUnavailableError`` on transient failures (HTTP 429/5xx,
    network errors, timeouts) and ``ValueError`` on everything else.
    """
    payload = {
        "model": model_id,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
    }
    request = Request(
        _get_endpoint(config),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_get_api_key(config)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = config.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    try:
        # Scheme is validated as https in _get_endpoint.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 429 or exc.code >= 500:
            raise RerankerUnavailableError(
                f"Rerank unavailable (HTTP {exc.code}): {body}"
            ) from exc
        raise ValueError(f"Rerank failed (HTTP {exc.code}): {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise RerankerUnavailableError(f"Rerank unreachable: {exc}") from exc
    return parse_rerank_response(data, len(documents))
