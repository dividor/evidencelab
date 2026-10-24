"""Google Vertex AI reranker via Discovery Engine Ranking API."""

import logging
import os
from typing import Any, List, Optional, Sequence, Tuple

from google.api_core import exceptions as gax_exceptions

logger = logging.getLogger(__name__)

# The Ranking API scores at most this many records in one request.
VERTEX_RERANK_MAX_BATCH_SIZE = 1000
# Evidence Lab sends fewer per request. A heatmap cell can hand the reranker
# up to 5000 chunks of full text, and one request carrying that much is
# rejected or times out. Pointwise relevance scores are comparable across
# requests, so a search is scored in slices of this size.
DEFAULT_VERTEX_RERANK_BATCH_SIZE = 200


class RerankerUnavailableError(RuntimeError):
    """Raised when an external reranker is temporarily unavailable.

    Distinct from arbitrary errors so callers can fall back to no-rerank
    on known-transient cases (e.g. Google ``503 UNAVAILABLE``,
    ``DEADLINE_EXCEEDED``) without swallowing real bugs.
    """


# Errors we treat as transient and recoverable: search should still succeed
# (without the rerank step) rather than 500 to the user. Anything else
# propagates so an unexpected bug isn't silently masked.
_TRANSIENT_RERANK_ERRORS = (
    gax_exceptions.ServiceUnavailable,
    gax_exceptions.DeadlineExceeded,
    gax_exceptions.GatewayTimeout,
    gax_exceptions.InternalServerError,
)


def _load_batch_size() -> int:
    """Read ``VERTEX_RERANK_BATCH_SIZE`` from the environment.

    Unset means the default. A value that is set but not a whole number
    between 1 and the API's own ceiling stops the API at import, rather
    than silently reranking with a size nobody chose.
    """
    raw = os.environ.get("VERTEX_RERANK_BATCH_SIZE")
    if raw is None:
        return DEFAULT_VERTEX_RERANK_BATCH_SIZE
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"VERTEX_RERANK_BATCH_SIZE must be a whole number, got {raw!r}"
        ) from exc
    if not 1 <= value <= VERTEX_RERANK_MAX_BATCH_SIZE:
        raise ValueError(
            "VERTEX_RERANK_BATCH_SIZE must be between 1 and "
            f"{VERTEX_RERANK_MAX_BATCH_SIZE}, got {value}"
        )
    return value


VERTEX_RERANK_BATCH_SIZE = _load_batch_size()


def _rank_batch(
    client: Any,
    discoveryengine: Any,
    ranking_config: str,
    model_id: str,
    query: str,
    batch: Sequence[Tuple[int, str]],
    scores: List[float],
) -> None:
    """Score one slice of ``(document index, text)`` pairs into ``scores``.

    Raises ``RerankerUnavailableError`` on transient Google-side outages
    (``503 UNAVAILABLE``, ``DEADLINE_EXCEEDED``, ``504``, ``500``). A ``400
    INVALID_ARGUMENT`` is logged with the batch's size and re-raised: the
    request itself is wrong, which is a bug to fix, not a condition to hide.
    """
    records = [
        discoveryengine.RankingRecord(id=str(index), content=text)
        for index, text in batch
    ]
    request = discoveryengine.RankRequest(
        ranking_config=ranking_config,
        model=model_id,
        top_n=len(records),
        query=query,
        records=records,
    )
    try:
        response = client.rank(request=request)
    except _TRANSIENT_RERANK_ERRORS as exc:
        raise RerankerUnavailableError(
            f"Vertex Discovery Engine rank API unavailable: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    except gax_exceptions.InvalidArgument:
        logger.error(
            "Vertex rank API rejected a batch of %d records (%d characters of text)",
            len(records),
            sum(len(text) for _, text in batch),
        )
        raise

    for record in response.records:
        scores[int(record.id)] = record.score


def rerank_with_google_vertex(
    query: str,
    documents: List[str],
    model_id: str,
    batch_size: Optional[int] = None,
) -> List[float]:
    """Rerank documents using the Vertex AI Ranking API (Discovery Engine).

    Documents are scored in slices of ``batch_size`` records (default
    ``VERTEX_RERANK_BATCH_SIZE``) and the scores are returned in the
    documents' order. A document with no text is never sent, because the
    API rejects empty content; it scores ``0.0``, as does a record the API
    leaves out of its answer.

    Raises ``RerankerUnavailableError`` on transient Google-side outages so
    the caller can fall back to the unranked results.
    """
    from google.cloud import (
        discoveryengine_v1 as discoveryengine,  # type: ignore[attr-defined]
    )

    from pipeline.utilities.google_vertex_client import _load_gcp_project_id

    size = VERTEX_RERANK_BATCH_SIZE if batch_size is None else batch_size
    if size < 1:
        raise ValueError(f"batch_size must be at least 1, got {size}")

    project_id = _load_gcp_project_id()
    client = discoveryengine.RankServiceClient()
    ranking_config = client.ranking_config_path(
        project=project_id,
        location="global",
        ranking_config="default_ranking_config",
    )

    scores: List[float] = [0.0] * len(documents)
    indexed = [(index, text) for index, text in enumerate(documents) if text]
    batches = [indexed[start : start + size] for start in range(0, len(indexed), size)]
    if len(batches) > 1:
        logger.info(
            "Vertex rerank: %d records in %d requests (batch size %d)",
            len(indexed),
            len(batches),
            size,
        )
    for batch in batches:
        _rank_batch(
            client, discoveryengine, ranking_config, model_id, query, batch, scores
        )
    return scores
