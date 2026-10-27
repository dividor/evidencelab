"""Brief citations, the read side: the brief as the API returns it (originals
summarised, display sources expanded), the sections as the citation check
reads them, one stored original, and the trace of a displayed number.

See ``brief_citations`` (the facade) for the overall design.
"""

import copy
from typing import Any, Dict, List, Optional

from ui.backend.services.brief_citation_model import (
    DISPLAY_FIELDS,
    RUN_SUMMARY_FIELDS,
    BriefCitationError,
    _sources_by_id,
    cited_numbers_in_order,
    current_run,
    find_run,
    find_section,
    is_visible,
    require_current_format,
)
from ui.backend.services.brief_citation_runs import (
    _assign_numbers,
    _section_display_numbers,
)


def _display_source(
    source: Dict[str, Any], index: int, variants: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    out = {key: source.get(key) for key in DISPLAY_FIELDS}
    out["index"] = index
    out["sourceId"] = source["id"]
    if source.get("claimMatches") is not None:
        out["claimMatches"] = source["claimMatches"]
    if variants:
        out["variants"] = variants
    return out


def _agent_indices(run: Optional[Dict[str, Any]], source_id: str) -> List[int]:
    if run is None:
        return []
    return sorted(
        int(raw) for raw, sid in (run.get("mapping") or {}).items() if sid == source_id
    )


def _expand_section_sources(
    section: Dict[str, Any], sources_by_id: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    run = current_run(section)
    out = []
    for row in (section.get("renumbered") or {}).get("sources") or []:
        source = sources_by_id.get(row["sourceId"])
        if source is None:
            continue
        variants = [
            _display_source(sources_by_id[vid], row["index"])
            for vid in row.get("variantIds") or []
            if vid in sources_by_id
        ]
        expanded = _display_source(source, row["index"], variants)
        expanded["agentIndices"] = _agent_indices(run, row["sourceId"])
        expanded["runId"] = run["id"] if run else None
        out.append(expanded)
    return out


def _run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    summary = {key: run.get(key) for key in RUN_SUMMARY_FIELDS if key in run}
    summary["sourceCount"] = len(run.get("sources") or [])
    summary["citedCount"] = len(cited_numbers_in_order(run.get("content") or ""))
    return summary


def display_sections(content: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The visible sections as readers see them: renumbered content and
    display sources (``index`` = display number, plus ``sourceId``,
    ``agentIndices`` and ``runId`` for tracing). Used by the citation check."""
    require_current_format(content)
    sources_by_id = _sources_by_id(content)
    out = []
    for section in content.get("sections") or []:
        if not is_visible(section):
            continue
        out.append(
            {
                "id": section.get("id"),
                "title": section.get("title", ""),
                "status": "done",
                "content": (section.get("renumbered") or {}).get("content") or "",
                "sources": _expand_section_sources(section, sources_by_id),
                "unresolved": list(
                    (section.get("renumbered") or {}).get("unresolved") or []
                ),
            }
        )
    return out


def expand_for_read(content: Dict[str, Any]) -> Dict[str, Any]:
    """The brief as the API returns it: originals summarised, display sources
    expanded, the brief-wide list itself left out (every consumer reads the
    expanded sections and references)."""
    require_current_format(content)
    sources_by_id = _sources_by_id(content)
    out = {
        key: copy.deepcopy(value) for key, value in content.items() if key != "sources"
    }
    out["sections"] = []
    for section in content.get("sections") or []:
        read = {k: copy.deepcopy(v) for k, v in section.items() if k != "runs"}
        read["runs"] = [_run_summary(run) for run in section.get("runs") or []]
        read["renumbered"] = {
            **copy.deepcopy(section.get("renumbered") or {}),
            "sources": _expand_section_sources(section, sources_by_id),
        }
        out["sections"].append(read)
    for ref in out.get("references") or []:
        source = sources_by_id.get(ref["sourceId"])
        ref["source"] = _display_source(source, ref["n"]) if source else None
    return out


def run_detail(content: Dict[str, Any], section_id: str, run_id: str) -> Dict[str, Any]:
    """One stored original, with its mapping and the agent -> display table."""
    require_current_format(content)
    section = find_section(content, section_id)
    run = find_run(section, run_id)
    if run is None:
        raise BriefCitationError("Run not found or no longer retained")
    sources_by_id = _sources_by_id(content)
    display = {}
    if section.get("currentRunId") == run_id:
        numbers = _section_display_numbers(
            run,
            _assign_numbers(content, sources_by_id)[0],
            sources_by_id,
            content["referenceGrouping"],
        )
        display = {str(agent_n): n for agent_n, (n, _sid) in numbers.items()}
    return {**copy.deepcopy(run), "displayNumbers": display, "sectionId": section_id}


def trace(content: Dict[str, Any], section_id: str, n: int) -> Dict[str, Any]:
    """Where a displayed ``[n]`` in a section came from."""
    require_current_format(content)
    section = find_section(content, section_id)
    run = current_run(section)
    row = next(
        (
            r
            for r in (section.get("renumbered") or {}).get("sources") or []
            if r["index"] == n
        ),
        None,
    )
    if run is None or row is None:
        raise BriefCitationError(f"[{n}] is not displayed in section {section_id}")
    source = _sources_by_id(content).get(row["sourceId"]) or {}
    agent_indices = _agent_indices(run, row["sourceId"])
    return {
        "n": n,
        "sourceId": row["sourceId"],
        "chunkId": source.get("chunkId"),
        "docId": source.get("docId"),
        "title": source.get("title"),
        "page": source.get("page"),
        "runId": run["id"],
        "agentIndices": agent_indices,
        "agentSources": [
            src for src in run.get("sources") or [] if src.get("index") in agent_indices
        ],
    }
