"""TOC validator service.

Runs the section-inclusion check (``pipeline.validation.section_inclusion``) over
documents and persists the result on each document row under the
``sys_toc_validation`` field (merged into ``sys_data`` via
``PostgresClient.merge_doc_sys_fields`` — the same mechanism used for
``sys_toc_approved``). No schema migration is required: the per-source
``docs_<source>`` tables auto-create ``sys_*`` columns on write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pipeline.db import PostgresClient
from pipeline.db.config import get_default_included_section_types
from pipeline.validation.section_inclusion import evaluate_document

# Field name stored on each document row (in sys_data + its own column).
SYS_FIELD = "sys_toc_validation"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_result(
    doc: Dict[str, Any],
    doc_id: str,
    validated_by: Optional[str],
    validated_at: str,
    included: List[str],
) -> Dict[str, Any]:
    """Evaluate a document row and shape the persisted/returned result."""
    evaluation = evaluate_document(doc, included=included)
    return {
        "doc_id": str(doc_id),
        "status": evaluation["status"],
        "range_start": evaluation["range_start"],
        "range_end": evaluation["range_end"],
        "sections_in_range": evaluation["sections_in_range"],
        "num_excluded": evaluation["num_excluded"],
        "excluded_section_types": evaluation["excluded_section_types"],
        "excluded_sections": evaluation["excluded_sections"],
        "reasons": evaluation["reasons"],
        "validated_at": validated_at,
        "validated_by": validated_by,
    }


def run_validation(
    pg: PostgresClient,
    doc_ids: List[str],
    validated_by: Optional[str] = None,
    validated_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Validate each document, persist the result, and return the results.

    Unknown ``doc_ids`` (not present in the table) are skipped silently.
    """
    stamp = validated_at or _now_iso()
    included = get_default_included_section_types()
    docs = pg.fetch_docs(doc_ids)
    results: List[Dict[str, Any]] = []
    for doc_id in doc_ids:
        doc = docs.get(str(doc_id))
        if doc is None:
            continue
        result = build_result(doc, str(doc_id), validated_by, stamp, included)
        pg.merge_doc_sys_fields(doc_id=str(doc_id), sys_fields={SYS_FIELD: result})
        results.append(result)
    return results


def get_stored_results(
    pg: PostgresClient, doc_ids: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """Return previously-stored validation results keyed by doc_id."""
    sys_map = pg.fetch_doc_sys_fields(doc_ids)
    results: Dict[str, Dict[str, Any]] = {}
    for doc_id, sys_data in sys_map.items():
        stored = (sys_data or {}).get(SYS_FIELD)
        if stored:
            results[str(doc_id)] = stored
    return results
