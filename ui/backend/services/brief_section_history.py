"""Brief citations, a section's history: the change awaiting review (Keep or
Reject), restoring an earlier version from the section's Log, and what the
Log says about each of its rows.

Every run of a section writes a Log row (``sections[].audit[]``) holding the
text readers saw before and after it and, for the text after it, which brief
source each displayed number pointed to (``afterSources``). Brief-wide
sources are never removed, so a row restores exactly from that alone, even
once its run has been trimmed away (see ``apply_retention``).

A single-section Generate, Edit or Update leaves ``pendingReview`` on the
section, in the stored brief, until it is kept, rejected or superseded by the
section's next change (see ``brief_citation_runs._next_review``).

See ``brief_citations`` (the facade) for the overall design.
"""

from typing import Any, Dict, List, Optional, Tuple

from ui.backend.services.brief_citation_model import (
    AUDIT_REJECTED,
    RUN_CURRENT,
    RUN_REJECTED,
    BriefCitationError,
    _display_record,
    _sources_by_id,
    find_run,
    find_section,
    require_current_format,
)
from ui.backend.services.brief_citation_runs import record_run, renumber


def _pending(section: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    pending = section.get("pendingReview") or {}
    if pending.get("runId") != run_id or section.get("currentRunId") != run_id:
        raise BriefCitationError("This change is no longer awaiting review")
    return pending


def keep_review(
    content: Dict[str, Any], section_id: str, run_id: str
) -> Dict[str, Any]:
    """Keep Edits: the change stays and is no longer awaiting review."""
    require_current_format(content)
    section = find_section(content, section_id)
    _pending(section, run_id)
    section.pop("pendingReview")
    return content


def reject_run(
    content: Dict[str, Any],
    section_id: str,
    run_id: str,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Reject Edits: the section goes back to the text it had before the
    change awaiting review. Every run of that change (a condense pass
    included) is marked rejected, and so are their Log rows, which stay."""
    require_current_format(content)
    section = find_section(content, section_id)
    pending = _pending(section, run_id)
    base = find_run(section, pending.get("baseRunId") or "")
    if base is None:
        raise BriefCitationError("The version before this change is no longer kept")
    later = section["runs"][section["runs"].index(base) + 1 :]
    rejected_ids = {run["id"] for run in later}
    for run in later:
        run["status"] = RUN_REJECTED
    for entry in section.get("audit") or []:
        if entry.get("runId") in rejected_ids:
            entry["status"] = AUDIT_REJECTED
    base["status"] = RUN_CURRENT
    section["currentRunId"] = base["id"]
    section["status"] = "done"
    section.pop("pendingReview")
    return renumber(content, now_ms)


def _records_for(
    numbering: Dict[str, str], sources_by_id: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Agent-style source records (``index`` = the number in the text) for a
    number -> brief source id table."""
    out = []
    for number, source_id in sorted(numbering.items(), key=lambda kv: int(kv[0])):
        source = sources_by_id.get(source_id)
        if source is not None:
            out.append({**_display_record(source), "index": int(number)})
    return out


def restorable_text(
    content: Dict[str, Any], section: Dict[str, Any], entry: Dict[str, Any]
) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """The text and sources a Log row's version restores from, or None.

    A row written since version history began carries its text and numbering
    (``after`` + ``afterSources``). An older row restores from its run while
    the run is still kept; otherwise it can only be viewed."""
    sources_by_id = _sources_by_id(content)
    if entry.get("after") is not None and entry.get("afterSources") is not None:
        return entry["after"], _records_for(entry["afterSources"], sources_by_id)
    run = find_run(section, entry.get("runId") or "")
    if run is None or entry.get("after") is None:
        return None
    return run["content"], _records_for(run.get("mapping") or {}, sources_by_id)


def current_entry_id(section: Dict[str, Any]) -> Optional[str]:
    """The Log row whose text the section shows now: the latest one not
    rejected, while the section has text."""
    if not section.get("currentRunId"):
        return None
    for entry in reversed(section.get("audit") or []):
        if entry.get("status") != AUDIT_REJECTED:
            return entry.get("id")
    return None


def annotate_audit(content: Dict[str, Any], section: Dict[str, Any]) -> List[Any]:
    """The section's Log rows as the API returns them: each says whether it
    is the version shown now and whether it can be restored."""
    current_id = current_entry_id(section)
    rows = []
    for entry in section.get("audit") or []:
        row = dict(entry)
        row["current"] = entry.get("id") == current_id
        row["restorable"] = not row["current"] and (
            restorable_text(content, section, entry) is not None
        )
        rows.append(row)
    return rows


def restore_section_version(
    content: Dict[str, Any],
    section_id: str,
    entry_id: str,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Restore the version of a section a Log row records. It is recorded as
    a new ``restore`` run, so nothing is removed and the Log gains a row."""
    require_current_format(content)
    section = find_section(content, section_id)
    entry = next(
        (e for e in section.get("audit") or [] if e.get("id") == entry_id), None
    )
    if entry is None:
        raise BriefCitationError(f"Unknown Log entry: {entry_id}")
    if entry_id == current_entry_id(section):
        raise BriefCitationError("This is already the section's current version")
    restorable = restorable_text(content, section, entry)
    if restorable is None:
        raise BriefCitationError("This version can no longer be restored")
    text, sources = restorable
    return record_run(
        content,
        section_id,
        {
            "mode": "restore",
            "content": text,
            "sources": sources,
            "restoredFrom": {
                "entryId": entry_id,
                "kind": entry.get("kind"),
                "at": entry.get("at"),
            },
        },
        now_ms,
    )
