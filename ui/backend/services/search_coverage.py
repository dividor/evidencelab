"""Result-concentration detection for chunk search.

A broad query (e.g. "targeting") can concentrate the highest-scoring chunks
in a handful of documents, so the results page shows only a few documents
even though many more match the query. The functions here compare the
documents visible on the returned page against the documents present in the
retrieval candidate pool (which the search already fetches before
truncation), so the API can tell the frontend when that situation occurred.

Thresholds are read from ``config.json`` under
``application.search.coverage_alert`` and fall back to the defaults below,
matching how the rest of the search configuration is loaded
(see ``ui/backend/services/search_models.py``).
"""

from dataclasses import dataclass
from typing import Any, Iterable

from pipeline.db import get_application_config

DEFAULT_MAX_DOCUMENT_FRACTION = 0.15
DEFAULT_MIN_DOCUMENT_FLOOR = 3
DEFAULT_CANDIDATE_RATIO = 3.0


@dataclass(frozen=True)
class CoverageThresholds:
    """Configurable trigger rule for the concentrated-results alert.

    Attributes:
        enabled: Master switch; when False the alert never triggers.
        max_document_fraction: The page counts as concentrated when its
            distinct documents are at most this fraction of the returned
            chunks (subject to ``min_document_floor``).
        min_document_floor: Lower bound on the concentration ceiling so
            small result pages behave sensibly.
        candidate_ratio: The candidate pool must contain at least this many
            times more distinct documents than the page for the alert to
            trigger — evidence that the corpus holds documents the user is
            not seeing.
    """

    enabled: bool = True
    max_document_fraction: float = DEFAULT_MAX_DOCUMENT_FRACTION
    min_document_floor: int = DEFAULT_MIN_DOCUMENT_FLOOR
    candidate_ratio: float = DEFAULT_CANDIDATE_RATIO


def load_coverage_thresholds() -> CoverageThresholds:
    """Load the trigger thresholds from ``application.search.coverage_alert``."""
    search_config = get_application_config().get("search", {})
    raw = search_config.get("coverage_alert", {})
    return CoverageThresholds(
        enabled=bool(raw.get("enabled", True)),
        max_document_fraction=float(
            raw.get("max_document_fraction", DEFAULT_MAX_DOCUMENT_FRACTION)
        ),
        min_document_floor=int(
            raw.get("min_document_floor", DEFAULT_MIN_DOCUMENT_FLOOR)
        ),
        candidate_ratio=float(raw.get("candidate_ratio", DEFAULT_CANDIDATE_RATIO)),
    )


def count_candidate_documents(point_lists: Iterable[Iterable[Any]]) -> int:
    """Count distinct documents across lists of Qdrant chunk points.

    Used on the pre-truncation retrieval pool (dense + sparse candidates),
    so no extra queries are needed to know how many documents matched.

    Args:
        point_lists: Iterables of Qdrant points whose payload carries
            ``doc_id`` (or legacy ``sys_doc_id``).

    Returns:
        Number of distinct document IDs found.
    """
    doc_ids = set()
    for points in point_lists:
        for point in points:
            payload = getattr(point, "payload", None) or {}
            doc_id = payload.get("doc_id") or payload.get("sys_doc_id")
            if doc_id:
                doc_ids.add(str(doc_id))
    return len(doc_ids)


def is_concentrated(
    chunks_returned: int,
    documents_in_results: int,
    candidate_documents: int,
    thresholds: CoverageThresholds,
) -> bool:
    """Decide whether the returned page is concentrated in few documents.

    Both conditions must hold: the page is dominated by a handful of
    documents, AND the candidate pool demonstrates that substantially more
    documents matched the query. The second condition is what keeps genuinely
    narrow queries (few matching documents corpus-wide) from triggering.

    Args:
        chunks_returned: Number of chunks on the returned page.
        documents_in_results: Distinct documents on the returned page.
        candidate_documents: Distinct documents in the retrieval pool.
        thresholds: Trigger rule configuration.

    Returns:
        True when the concentrated-results alert should be shown.
    """
    if not thresholds.enabled:
        return False
    if chunks_returned <= 0 or documents_in_results <= 0:
        return False
    concentration_ceiling = max(
        thresholds.min_document_floor,
        thresholds.max_document_fraction * chunks_returned,
    )
    if documents_in_results > concentration_ceiling:
        return False
    return candidate_documents >= thresholds.candidate_ratio * documents_in_results
