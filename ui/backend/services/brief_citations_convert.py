"""Convert a brief stored before citation format 2.

A legacy brief keeps each section's agent output as ``sections[].content``
and ``sections[].sources`` and renumbers only in the browser. The
conversion treats that content and those sources as the section's one
original run, registers every source into the brief-wide list, and computes
the renumbered version with :mod:`brief_citations`, the same code every new
brief goes through. It is used by the reviewed CLI
(``scripts/fixes/convert_brief_citations.py``, dry run by default) and by the
Alembic data migration that runs it on deploy.

The report returned beside the converted content says, per brief, how many
markers were converted, which had no source, how many source records had no
chunk id, and the sizes before and after. :func:`compare_with_legacy` checks
the result against what the browser's ``buildGlobalCitations`` produced for
the same rows (``scripts/fixes/brief_citations_legacy``).
"""

import copy
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ui.backend.services import brief_citations as bc

# Section fields carried over from a legacy section as they are.
_SECTION_FIELDS = (
    "id",
    "title",
    "level",
    "status",
    "guidance",
    "voiceId",
    "targetWords",
    "introHeadingWarning",
    "lastResearchedAt",
    "sample",
)
_HIGHLIGHT_FIELDS = ("claimMatches", "semanticMatches")

COMPARE_EQUAL = "equal"
COMPARE_SAME_CITATIONS = "same-citations-different-numbers"
COMPARE_DIFFERS = "differs"


def is_legacy(content: Dict[str, Any]) -> bool:
    return (content or {}).get("citationsVersion") != bc.CITATIONS_VERSION


def _legacy_section(section: Dict[str, Any], position: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        key: section[key] for key in _SECTION_FIELDS if key in section
    }
    out.setdefault("id", f"sec{position + 1}")
    out.setdefault("status", "pending")
    out["runs"] = []
    out["currentRunId"] = None
    out["audit"] = copy.deepcopy(section.get("audit") or [])
    return out


def _carry_highlights(
    content: Dict[str, Any], legacy_sources: List[Dict[str, Any]]
) -> None:
    """Highlights computed for a legacy source move to its brief-wide entry."""
    by_chunk = {src.get("chunkId"): src for src in content["sources"]}
    for legacy in legacy_sources:
        entry = by_chunk.get(legacy.get("chunkId"))
        if entry is None or entry.get("claimMatches") is not None:
            continue
        for key in _HIGHLIGHT_FIELDS:
            if legacy.get(key) is not None:
                entry["claimMatches"] = legacy[key]
                break


def _link_audit(section: Dict[str, Any], run_id: str) -> None:
    """The legacy Log rows stay; the latest one names the run it describes.
    The entry ``record_run`` appended is dropped in its favour, unless the
    section had no Log at all."""
    appended = section["audit"].pop()
    if not section["audit"]:
        section["audit"].append(appended)
        return
    section["audit"][-1]["runId"] = run_id
    section["audit"][-1]["unresolvedCount"] = appended["unresolvedCount"]


def _convert_section(
    content: Dict[str, Any],
    legacy: Dict[str, Any],
    section: Dict[str, Any],
    report: Dict[str, Any],
    now_ms: Optional[int],
) -> None:
    text = legacy.get("content") or ""
    if legacy.get("status") != "done" or not text.strip():
        section["status"] = "pending"
        return
    sources = copy.deepcopy(legacy.get("sources") or [])
    at = legacy.get("lastResearchedAt") or content.get("date") or now_ms
    bc.record_run(
        content,
        section["id"],
        {
            "mode": "generate",
            "content": text,
            "sources": sources,
            "question": section.get("title"),
        },
        now_ms=at,
    )
    run = bc.current_run(section)
    if run is None:
        raise RuntimeError(f"Run not recorded for section {section['id']}")
    _link_audit(section, run["id"])
    _carry_highlights(content, sources)
    markers = bc.cited_numbers_in_order(text)
    report["sections"].append(
        {
            "id": section["id"],
            "title": section.get("title"),
            "runId": run["id"],
            "markers": len(markers),
            "unresolved": [u["n"] for u in run["unresolved"]],
            "sourcesNoChunkId": len(run["rejected"]),
            "sourceRecords": len(sources),
        }
    )
    report["markers"] += len(markers)
    report["markersNoSource"] += len(run["unresolved"])
    report["sourcesNoChunkId"] += len(run["rejected"])


def convert_legacy(
    content: Dict[str, Any], now_ms: Optional[int] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(converted content, report)`` for one legacy brief.

    Raises ``ValueError`` when the brief is already in format 2.
    """
    if not is_legacy(content):
        raise ValueError("Brief is already in citation format 2")
    legacy_sections = content.get("sections") or []
    converted: Dict[str, Any] = {
        key: copy.deepcopy(value) for key, value in content.items() if key != "sections"
    }
    converted["citationsVersion"] = bc.CITATIONS_VERSION
    converted["referenceGrouping"] = bc.GROUPING_PASSAGE
    converted["sources"] = []
    converted["sections"] = [
        _legacy_section(section, i) for i, section in enumerate(legacy_sections)
    ]
    report: Dict[str, Any] = {
        "sections": [],
        "markers": 0,
        "markersNoSource": 0,
        "sourcesNoChunkId": 0,
        "bytesBefore": len(json.dumps(content, default=str)),
    }
    for legacy, section in zip(legacy_sections, converted["sections"]):
        _convert_section(converted, legacy, section, report, now_ms)
    bc.renumber(converted, now_ms)
    report["sourcesRegistered"] = len(converted["sources"])
    report["bytesAfter"] = len(json.dumps(converted, default=str))
    return converted, report


# ---------------------------------------------------------------------------
# The brief's Activity row, for writers without the ORM (script, migration)
# ---------------------------------------------------------------------------


def refresh_activity_row(
    conn: Any, brief_id: Any, user_id: Any, title: str, content: Dict[str, Any]
) -> bool:
    """Rewrite the brief's Activity row from its (format 2) content with a
    plain SQL update on ``conn`` (a SQLAlchemy connection), as the API does
    on every save. Returns False when the brief has no row to refresh."""
    import json as _json
    import uuid as _uuid

    from sqlalchemy import text

    from ui.backend.services.brief_activity import activity_row_values

    raw = content.get("activityId")
    try:
        search_id = _uuid.UUID(str(raw)) if raw else None
    except ValueError:
        search_id = None
    if search_id is None:
        return False
    row = conn.execute(
        text(
            "SELECT id, filters FROM user_activity WHERE search_id = :sid AND user_id = :uid"
        ),
        {"sid": search_id, "uid": user_id},
    ).fetchone()
    if row is None:
        return False
    values = activity_row_values(content, title, brief_id, row[1])
    conn.execute(
        text(
            "UPDATE user_activity SET query = :query, filters = CAST(:filters AS jsonb), "
            "search_results = CAST(:results AS jsonb), ai_summary = :summary WHERE id = :id"
        ),
        {
            "query": values["query"],
            "filters": _json.dumps(values["filters"]),
            "results": _json.dumps(values["search_results"]),
            "summary": values["ai_summary"],
            "id": row[0],
        },
    )
    return True


# ---------------------------------------------------------------------------
# Comparison with the browser's buildGlobalCitations output
# ---------------------------------------------------------------------------


def _citation_sequence(
    text: str, chunk_of: Dict[int, Optional[str]]
) -> List[List[Optional[str]]]:
    """The chunk ids each marker of the text points at, in order."""
    return [
        [chunk_of.get(n) for n in bc.parse_marker_numbers(m.group(1))]
        for m in bc.CITATION_RE.finditer(text)
    ]


def _without_markers(text: str) -> str:
    text = bc.CITATION_RE.sub("", text)
    text = bc.UNRESOLVED_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _new_chunk_of(
    section: Dict[str, Any], content: Dict[str, Any]
) -> Dict[int, Optional[str]]:
    sources = {src["id"]: src for src in content["sources"]}
    return {
        row["index"]: sources.get(row["sourceId"], {}).get("chunkId")
        for row in section["renumbered"]["sources"]
    }


def compare_section(
    section: Dict[str, Any], content: Dict[str, Any], legacy: Dict[str, Any]
) -> str:
    """``equal`` when the renumbered text matches the browser's output
    exactly; ``same-citations-different-numbers`` when every marker points at
    the same chunks and only the numbers differ (reading order versus the
    browser's numeric order, or a ``[?n]`` where the browser dropped the
    marker); ``differs`` otherwise."""
    new_text = section["renumbered"]["content"]
    old_text = legacy.get("content") or ""
    old_chunk_of = {s["index"]: s.get("chunkId") for s in legacy.get("sources") or []}
    same_cites = _citation_sequence(
        new_text, _new_chunk_of(section, content)
    ) == _citation_sequence(old_text, old_chunk_of)
    if not same_cites:
        return COMPARE_DIFFERS
    if new_text == old_text:
        return COMPARE_EQUAL
    same_text = _without_markers(new_text) == _without_markers(old_text)
    return COMPARE_SAME_CITATIONS if same_text else COMPARE_DIFFERS


def compare_with_legacy(
    content: Dict[str, Any], legacy: Dict[str, Any]
) -> Dict[str, Any]:
    """Compare a converted brief with the browser's rendering of the same
    legacy rows (``{sections: {id: {content, sources}}, refs: [...]}``)."""
    per_section = {}
    for section in content["sections"]:
        if not bc.is_visible(section):
            continue
        legacy_section = (legacy.get("sections") or {}).get(section["id"])
        per_section[section["id"]] = (
            compare_section(section, content, legacy_section)
            if legacy_section
            else "missing-in-legacy"
        )
    new_refs = [
        (r["n"], _chunk_of_source(content, r["sourceId"]), r["page"])
        for r in content["references"]
    ]
    old_refs = [
        (r["n"], r.get("chunkId"), r.get("page")) for r in legacy.get("refs") or []
    ]
    return {
        "sections": per_section,
        "referencesEqual": new_refs == old_refs,
        "referenceCount": (len(new_refs), len(old_refs)),
    }


def _chunk_of_source(content: Dict[str, Any], source_id: str) -> Optional[str]:
    for src in content["sources"]:
        if src["id"] == source_id:
            return src.get("chunkId")
    return None


__all__ = [
    "COMPARE_DIFFERS",
    "COMPARE_EQUAL",
    "COMPARE_SAME_CITATIONS",
    "compare_with_legacy",
    "convert_legacy",
    "is_legacy",
    "refresh_activity_row",
]
