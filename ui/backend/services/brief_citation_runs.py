"""Brief citations, the operations: register a run's sources into the
brief-wide list, record and retire runs, and renumber the whole brief.

See ``brief_citations`` (the facade) for the overall design.
"""

import copy
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ui.backend.services.brief_citation_model import (
    BRIEF_SETTING_FIELDS,
    CITATION_RE,
    GROUPING_DOC_SINGLE,
    GROUPINGS,
    MAX_CONTENT_CHARS,
    REASON_NO_CHUNK,
    RETAINED_TRIMMED_RUNS,
    RUN_CURRENT,
    RUN_MODES,
    RUN_REJECTED,
    RUN_SUPERSEDED,
    SECTION_STRUCTURE_FIELDS,
    SOURCES_EXACT,
    SOURCES_TRIMMED,
    BriefCitationError,
    BriefTooLargeError,
    _all_run_ids,
    _display_record,
    _ensure_lists,
    _fill_missing,
    _next_id,
    _now_ms,
    _sources_by_id,
    cited_numbers_in_order,
    collapse_adjacent_duplicates,
    current_run,
    find_run,
    find_section,
    is_visible,
    parse_marker_numbers,
    require_current_format,
    strip_leading_title,
    unresolved_markers,
)


def register_sources(
    content: Dict[str, Any],
    section_id: str,
    run_id: str,
    agent_sources: List[Dict[str, Any]],
    now_ms: Optional[int] = None,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Register every agent source record into the brief-wide list.

    Returns ``(mapping, rejected)``: the agent's ``index`` -> brief source id
    (keys are strings, as stored in JSON), and the records refused because
    they carry no chunk id.
    """
    _ensure_lists(content)
    by_chunk = {src["chunkId"]: src for src in content["sources"]}
    mapping: Dict[str, str] = {}
    rejected: List[Dict[str, Any]] = []
    for agent_source in agent_sources:
        index = agent_source.get("index")
        chunk_id = agent_source.get("chunkId")
        if not chunk_id:
            rejected.append({"index": index, "reason": REASON_NO_CHUNK})
            continue
        entry = by_chunk.get(chunk_id)
        if entry is None:
            entry = {
                "id": _next_id("s", (s["id"] for s in content["sources"])),
                **_display_record(agent_source),
                "registeredAt": _now_ms(now_ms),
                "registeredBy": {"sectionId": section_id, "runId": run_id},
            }
            content["sources"].append(entry)
            by_chunk[chunk_id] = entry
        else:
            _fill_missing(entry, agent_source)
        if index is not None:
            mapping[str(index)] = entry["id"]
    return mapping, rejected


def _doc_ids(sources: Iterable[Dict[str, Any]]) -> set:
    return {src.get("docId") for src in sources if src.get("docId")}


def _audit_entry(
    run: Dict[str, Any], previous: Optional[Dict[str, Any]], note: Optional[str]
) -> Dict[str, Any]:
    """The Log row for a run; a revise keeps before/after for its diff view."""
    prior_docs = _doc_ids(previous.get("sources") or []) if previous else set()
    added = len(_doc_ids(run["sources"]) - prior_docs)
    entry: Dict[str, Any] = {
        "id": f"a-{run['id']}",
        "kind": run["mode"],
        "at": run["at"],
        "runId": run["id"],
        "sourceCount": len(run["sources"]),
        "addedSourceCount": added if previous else 0,
        "unresolvedCount": len(run["unresolved"]),
    }
    for key in ("question", "instruction"):
        if run.get(key):
            entry[key] = run[key]
    if note:
        entry["note"] = note
    if run["mode"] != "generate" and previous is not None:
        entry["before"] = previous.get("content") or ""
        entry["after"] = run["content"]
    return entry


def _validate_run_input(run: Dict[str, Any]) -> None:
    if run.get("mode") not in RUN_MODES:
        raise BriefCitationError(f"Unknown run mode: {run.get('mode')!r}")
    if not isinstance(run.get("content"), str):
        raise BriefCitationError("Run content must be a string")
    sources = run.get("sources")
    if sources is not None and not isinstance(sources, list):
        raise BriefCitationError("Run sources must be a list")


def display_numbering(section: Dict[str, Any]) -> Dict[str, str]:
    """Display number -> brief source id, as the section is shown right now."""
    return {
        str(row["index"]): row["sourceId"]
        for row in (section.get("renumbered") or {}).get("sources") or []
    }


def _display_sources(
    section: Dict[str, Any], sources_by_id: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """The section's display sources as agent-style records (``index`` = the
    display number): the sources of a run whose text was written against the
    numbers on screen (an AI edit, a condense pass, a manual edit)."""
    out = []
    for row in (section.get("renumbered") or {}).get("sources") or []:
        source = sources_by_id.get(row["sourceId"])
        if source is None:
            continue
        record = _display_record(source)
        record["index"] = row["index"]
        out.append(record)
    return out


def _check_based_on(
    section: Dict[str, Any], based_on: Optional[Dict[str, Any]]
) -> None:
    """A revise run names the numbering its text was written against; if the
    section has been renumbered since, its markers would point elsewhere."""
    if based_on is None:
        return
    current = display_numbering(section)
    if {str(k): v for k, v in based_on.items()} != current:
        raise BriefCitationError(
            "The section was renumbered after this text was fetched; reload the brief"
        )


def record_run(
    content: Dict[str, Any],
    section_id: str,
    run: Dict[str, Any],
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Store a run's original output, map it and renumber the brief.

    ``run``: ``{mode, content, sources?, basedOn?, runId?, question?, instruction?,
    note?}``. ``sources`` omitted means the text was written against the
    section's display numbering (an AI edit, a condense pass, a manual edit):
    the run's sources are then the display sources, numbered as shown, and
    ``basedOn`` (display number -> source id, as the client saw it) guards
    against a renumbering in between.
    """
    require_current_format(content)
    _ensure_lists(content)
    _validate_run_input(run)
    section = find_section(content, section_id)
    previous = current_run(section)
    sources = run.get("sources")
    if sources is None:
        _check_based_on(section, run.get("basedOn"))
        sources = _display_sources(section, _sources_by_id(content))
    run_id = _next_id("r", _all_run_ids(content))
    mapping, rejected = register_sources(content, section_id, run_id, sources, now_ms)
    stored: Dict[str, Any] = {
        "id": run_id,
        "mode": run["mode"],
        "at": _now_ms(now_ms),
        "content": run["content"],
        "sources": copy.deepcopy(sources),
        "sourcesRetained": SOURCES_EXACT,
        "mapping": mapping,
        "rejected": rejected,
        "unresolved": unresolved_markers(run["content"], mapping, rejected),
        "status": RUN_CURRENT,
    }
    for key in ("runId", "question", "instruction"):
        if run.get(key):
            stored[key] = run[key]
    if previous is not None:
        previous["status"] = RUN_SUPERSEDED
    section["runs"].append(stored)
    section["currentRunId"] = run_id
    section["status"] = "done"
    section["audit"].append(_audit_entry(stored, previous, run.get("note")))
    apply_retention(section)
    return renumber(content, now_ms)


def _trim_run(run: Dict[str, Any]) -> None:
    """Keep only the cited records, without their excerpt, of an older run."""
    if run.get("sourcesRetained") == SOURCES_TRIMMED:
        return
    cited = set(cited_numbers_in_order(run.get("content") or ""))
    kept = []
    for src in run.get("sources") or []:
        if src.get("index") in cited:
            kept.append({k: v for k, v in src.items() if k != "text"})
    run["sources"] = kept
    run["sourcesRetained"] = SOURCES_TRIMMED


def apply_retention(section: Dict[str, Any]) -> None:
    """Latest and current runs stay exact; the next four are trimmed; older go."""
    runs = section.get("runs") or []
    if not runs:
        return
    exact = {runs[-1]["id"], section.get("currentRunId")}
    others = [run for run in runs if run["id"] not in exact]
    keep = others[-RETAINED_TRIMMED_RUNS:] if RETAINED_TRIMMED_RUNS else []
    for run in keep:
        _trim_run(run)
    kept_ids = exact | {run["id"] for run in keep}
    section["runs"] = [run for run in runs if run["id"] in kept_ids]


def reject_run(
    content: Dict[str, Any],
    section_id: str,
    run_id: str,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Reject edits: the run before the current one becomes current again."""
    require_current_format(content)
    section = find_section(content, section_id)
    run = find_run(section, run_id)
    if run is None or section.get("currentRunId") != run_id:
        raise BriefCitationError("Only the current run can be rejected")
    run["status"] = RUN_REJECTED
    earlier = [
        r
        for r in section["runs"][: section["runs"].index(run)]
        if r.get("status") != RUN_REJECTED
    ]
    section["audit"] = [
        a for a in section.get("audit") or [] if a.get("runId") != run_id
    ]
    if earlier:
        earlier[-1]["status"] = RUN_CURRENT
        section["currentRunId"] = earlier[-1]["id"]
    else:
        section["currentRunId"] = None
        section["status"] = "pending"
    return renumber(content, now_ms)


def _citation_key(source: Dict[str, Any], grouping: str) -> str:
    """What a display number is assigned to: the chunk, or the document."""
    if grouping == GROUPING_DOC_SINGLE:
        return f"doc:{source.get('docId') or source.get('title')}"
    return f"src:{source['id']}"


def _assign_numbers(
    content: Dict[str, Any], sources_by_id: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Display numbers in reading order of first citation across the brief."""
    grouping = content["referenceGrouping"]
    key_to_n: Dict[str, int] = {}
    references: List[Dict[str, Any]] = []
    for section in content["sections"]:
        run = current_run(section)
        if not is_visible(section) or run is None:
            continue
        for number in cited_numbers_in_order(run["content"]):
            source_id = run["mapping"].get(str(number))
            if source_id is None or source_id not in sources_by_id:
                continue
            source = sources_by_id[source_id]
            key = _citation_key(source, grouping)
            if key in key_to_n:
                continue
            key_to_n[key] = len(references) + 1
            references.append(
                {
                    "n": key_to_n[key],
                    "sourceId": source_id,
                    "title": source.get("title") or "",
                    "page": (
                        None if grouping == GROUPING_DOC_SINGLE else source.get("page")
                    ),
                    "docId": source.get("docId") or "",
                }
            )
    return key_to_n, references


def _rewrite_marker(
    numbers: List[int], display_of: Callable[[int], Optional[int]]
) -> str:
    """``[1, 4]`` -> ``[12, 3]``; numbers with no source stay visible as ``[?n]``."""
    mapped: List[int] = []
    unresolved: List[int] = []
    for number in numbers:
        display = display_of(number)
        if display is None:
            unresolved.append(number)
        elif display not in mapped:
            mapped.append(display)
    out = f"[{', '.join(str(n) for n in mapped)}]" if mapped else ""
    return out + "".join(f"[?{n}]" for n in unresolved)


def _section_display_numbers(
    run: Dict[str, Any],
    key_to_n: Dict[str, int],
    sources_by_id: Dict[str, Dict[str, Any]],
    grouping: str,
) -> Dict[int, Tuple[int, str]]:
    """Agent number -> (display number, brief source id) for one section."""
    out: Dict[int, Tuple[int, str]] = {}
    for raw, source_id in (run.get("mapping") or {}).items():
        source = sources_by_id.get(source_id)
        if source is None:
            continue
        display = key_to_n.get(_citation_key(source, grouping))
        if display is not None:
            out[int(raw)] = (display, source_id)
    return out


def _section_sources(
    run: Dict[str, Any], numbers: Dict[int, Tuple[int, str]]
) -> List[Dict[str, Any]]:
    """The section's display sources: one per display number, in order of
    citation; other chunks sharing the number (per-document grouping) ride
    along as variants so the hover card can show the cited passage."""
    rows: Dict[int, Dict[str, Any]] = {}
    for number in cited_numbers_in_order(run["content"]):
        if number not in numbers:
            continue
        display, source_id = numbers[number]
        row = rows.get(display)
        if row is None:
            rows[display] = {"index": display, "sourceId": source_id, "variantIds": []}
        elif source_id != row["sourceId"] and source_id not in row["variantIds"]:
            row["variantIds"].append(source_id)
    return list(rows.values())


def _renumber_section(
    section: Dict[str, Any],
    key_to_n: Dict[str, int],
    sources_by_id: Dict[str, Dict[str, Any]],
    grouping: str,
    now_ms: int,
) -> None:
    run = current_run(section) if is_visible(section) else None
    if run is None:
        section["renumbered"] = {
            "content": "",
            "sources": [],
            "unresolved": [],
            "grouping": grouping,
            "computedAt": now_ms,
        }
        return
    numbers = _section_display_numbers(run, key_to_n, sources_by_id, grouping)

    def display_of(number: int) -> Optional[int]:
        return numbers[number][0] if number in numbers else None

    rewritten = CITATION_RE.sub(
        lambda m: _rewrite_marker(parse_marker_numbers(m.group(1)), display_of),
        strip_leading_title(run["content"], section.get("title") or ""),
    )
    section["renumbered"] = {
        "content": collapse_adjacent_duplicates(rewritten),
        "sources": _section_sources(run, numbers),
        "unresolved": list(run.get("unresolved") or []),
        "grouping": grouping,
        "computedAt": now_ms,
    }


def _reference_groups(references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per document with each of its numbers and pages, as the
    References list shows them with "Group by document (multiple)"."""
    groups: Dict[str, Dict[str, Any]] = {}
    for ref in references:
        key = ref["docId"] or ref["title"]
        group = groups.get(key)
        if group is None:
            group = {"docId": ref["docId"], "title": ref["title"], "cites": []}
            groups[key] = group
        group["cites"].append(
            {"n": ref["n"], "page": ref["page"], "sourceId": ref["sourceId"]}
        )
    for group in groups.values():
        group["cites"].sort(key=lambda c: (c["page"] or 0, c["n"]))
    return list(groups.values())


def renumber(content: Dict[str, Any], now_ms: Optional[int] = None) -> Dict[str, Any]:
    """Recompute every section's renumbered content and the References list."""
    require_current_format(content)
    _ensure_lists(content)
    if content["referenceGrouping"] not in GROUPINGS:
        raise BriefCitationError(f"Unknown grouping: {content['referenceGrouping']!r}")
    sources_by_id = _sources_by_id(content)
    key_to_n, references = _assign_numbers(content, sources_by_id)
    stamp = _now_ms(now_ms)
    for section in content["sections"]:
        _renumber_section(
            section, key_to_n, sources_by_id, content["referenceGrouping"], stamp
        )
    content["references"] = references
    content["referenceGroups"] = _reference_groups(references)
    content["sourceCount"] = len(content["sources"])
    content["sectionCount"] = len(content["sections"])
    content["renumberedAt"] = stamp
    check_size(content)
    return content


def set_grouping(
    content: Dict[str, Any], grouping: str, now_ms: Optional[int] = None
) -> Dict[str, Any]:
    if grouping not in GROUPINGS:
        raise BriefCitationError(f"Unknown grouping: {grouping!r}")
    require_current_format(content)
    content["referenceGrouping"] = grouping
    return renumber(content, now_ms)


def _new_section(section_id: str) -> Dict[str, Any]:
    return {
        "id": section_id,
        "title": "",
        "level": 1,
        "status": "pending",
        "runs": [],
        "audit": [],
        "currentRunId": None,
    }


def _merge_section(stored: Dict[str, Any], client: Dict[str, Any]) -> Dict[str, Any]:
    for key in SECTION_STRUCTURE_FIELDS:
        if key in client and key != "status":
            stored[key] = client[key]
    # A section's status follows its runs, never the client's snapshot: a
    # section with a current run is done (its text lives here, and a save
    # racing a research run must not hide it); one without is pending.
    stored["status"] = "done" if current_run(stored) is not None else "pending"
    return stored


def apply_structure(
    content: Dict[str, Any], client: Dict[str, Any], now_ms: Optional[int] = None
) -> Dict[str, Any]:
    """Take the client's structure and settings; keep every citation fact.

    Sections are matched by id and ordered as sent; a section left out is
    deleted with its runs (its registered sources keep their ids). A new
    section sent with ``content`` and no runs (template text) gets a manual
    run so that text is numbered like any other. A section's status is not
    taken from the client: it is done exactly when it has a current run.
    """
    require_current_format(content)
    _ensure_lists(content)
    stored = {s["id"]: s for s in content["sections"]}
    sections: List[Dict[str, Any]] = []
    texts: List[Tuple[str, str]] = []
    for client_section in client.get("sections") or []:
        section_id = client_section.get("id") or _next_id(
            "sec", [s["id"] for s in sections] + list(stored)
        )
        section = _merge_section(
            stored.get(section_id) or _new_section(section_id), client_section
        )
        sections.append(section)
        text = client_section.get("content") or ""
        if text.strip() and not section["runs"]:
            texts.append((section_id, text))
    content["sections"] = sections
    for key in BRIEF_SETTING_FIELDS:
        if key in client:
            content[key] = client[key]
    for section_id, text in texts:
        record_run(
            content,
            section_id,
            {"mode": "manual", "content": text, "sources": []},
            now_ms,
        )
    return renumber(content, now_ms)


def set_highlights(
    content: Dict[str, Any], highlights: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    """Store the highlighter's claim matches, by brief source id."""
    require_current_format(content)
    sources_by_id = _sources_by_id(content)
    for source_id, claim_matches in highlights.items():
        source = sources_by_id.get(source_id)
        if source is None:
            raise BriefCitationError(f"Unknown source: {source_id}")
        source["claimMatches"] = claim_matches
    return content


def check_size(content: Dict[str, Any]) -> None:
    size = len(json.dumps(content, default=str))
    if size > MAX_CONTENT_CHARS:
        raise BriefTooLargeError(
            f"Brief would be {size:,} characters, over the {MAX_CONTENT_CHARS:,} limit"
        )
