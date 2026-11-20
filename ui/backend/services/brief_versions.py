"""Whole-brief versions: what a version stores, what changed between two of
them, and restoring a brief to one.

A version (``brief_versions.content``) is a *snapshot* of the brief, not a
copy of ``briefs.content``. A stored brief is mostly source excerpts, held
in its brief-wide source list and again in each section's exact runs
(measured locally: about 785,000 characters a brief, over 95% of it
sources), and a brief changes dozens of times. Brief-wide sources are never
removed and keep their ids, so a snapshot keeps only what changes:

- the brief's settings (title, prompt, voice, length, grouping, outline log);
- each section's structure and settings, its *current* run (text, mapping
  from its numbers to brief source ids, unresolved markers; no source
  records) and its Log rows without their before/after text.

:func:`materialise` rebuilds a full brief from a snapshot and the brief's
current source list (a superset of every source the snapshot names), which
:func:`compare` renders and :func:`restore_brief` restores from.

Pure functions; ``brief_version_store`` writes and reads the table.
Tests: ``tests/unit/test_brief_versions.py``.
"""

import copy
import json
from typing import Any, Dict, List, Optional, Tuple

from ui.backend.services.brief_citation_model import (
    BRIEF_SETTING_FIELDS,
    RUN_CURRENT,
    RUN_SUPERSEDED,
    SOURCES_EXACT,
    _now_ms,
    _sources_by_id,
    current_run,
    find_run,
    require_current_format,
)
from ui.backend.services.brief_citation_runs import (
    apply_retention,
    check_size,
    complete_entry,
    renumber,
    section_display_text,
)
from ui.backend.services.brief_section_history import _records_for

# Brief keys a snapshot leaves out: the source list (kept by the brief) and
# what renumbering recomputes.
_BRIEF_DERIVED = (
    "sources",
    "sections",
    "references",
    "referenceGroups",
    "renumberedAt",
    "sourceCount",
)
# Section keys a snapshot leaves out or stores in another form.
_SECTION_DERIVED = ("runs", "renumbered", "pendingReview", "currentRunId", "audit")
# Log-row keys a snapshot leaves out (the text lives in the brief's own Log).
_AUDIT_TEXT = ("before", "after", "afterSources")
# Bookkeeping the browser updates on its own; a save that changes only these
# is not a new version.
_BRIEF_BOOKKEEPING = ("date", "sectionCount")
_SECTION_BOOKKEEPING = ("lastResearchedAt", "introHeadingWarning", "sample", "status")
# Settings a restore takes from the version; the brief keeps its own id and
# Activity row.
RESTORED_SETTINGS = tuple(
    key for key in BRIEF_SETTING_FIELDS if key not in ("id", "activityId")
) + ("referenceGrouping",)

# Kinds of version. Run modes name a change to one section.
KIND_CREATED = "created"
KIND_COPIED = "copied"
KIND_BASELINE = "baseline"
KIND_STRUCTURE = "structure"
KIND_SETTINGS = "settings"
KIND_GROUPING = "grouping"
KIND_REJECT = "reject"
KIND_BRIEF_RESTORE = "brief-restore"
# Saves the author makes while typing; several in a row by the same person
# merge into one version (see brief_version_store).
TYPING_KINDS = frozenset({KIND_STRUCTURE, KIND_SETTINGS, "manual"})

_SECTION_SUMMARIES = {
    "generate": "Researched “{title}”",
    # A generate run on a section that already had text.
    "regenerate": "Regenerated “{title}”",
    "edit": "Edited “{title}” with AI",
    "update": "Updated “{title}” with new sources",
    "condense": "Shortened “{title}” to its length target",
    "manual": "Edited “{title}” by hand",
    "restore": "Restored an earlier version of “{title}”",
    KIND_REJECT: "Rejected the changes to “{title}”",
}
_BRIEF_SUMMARIES = {
    KIND_CREATED: "Created the brief",
    KIND_COPIED: "Copied from “{detail}”",
    KIND_BASELINE: "The brief as it was when version history began",
    KIND_GROUPING: "Changed how citations are numbered",
    KIND_BRIEF_RESTORE: "Restored the whole brief to version {detail}",
}
_SETTING_PHRASES = {
    "title": "Renamed the brief",
    "query": "Changed the research question",
    "instructions": "Changed the brief prompt",
    "voiceId": "Changed the voice & tone",
    "targetWords": "Changed the length target",
    "numberHeadings": "Changed heading numbering",
    "referenceGrouping": "Changed how citations are numbered",
    "outlineLog": "Drafted the outline",
}
_SECTION_SETTING_KEYS = ("guidance", "voiceId", "targetWords")


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _section_snapshot(section: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        key: copy.deepcopy(value)
        for key, value in section.items()
        if key not in _SECTION_DERIVED
    }
    run = current_run(section)
    out["run"] = (
        {key: copy.deepcopy(value) for key, value in run.items() if key != "sources"}
        if run
        else None
    )
    out["audit"] = [
        {key: value for key, value in entry.items() if key not in _AUDIT_TEXT}
        for entry in section.get("audit") or []
    ]
    return out


def snapshot(content: Dict[str, Any]) -> Dict[str, Any]:
    """What a version stores of the brief (see the module docstring)."""
    require_current_format(content)
    out = {
        key: copy.deepcopy(value)
        for key, value in content.items()
        if key not in _BRIEF_DERIVED
    }
    out["sections"] = [_section_snapshot(s) for s in content.get("sections") or []]
    return out


def signature(snap: Dict[str, Any]) -> str:
    """A snapshot without the browser's bookkeeping, for telling whether a
    save changed anything a reader would call a change."""
    brief = {k: v for k, v in snap.items() if k not in _BRIEF_BOOKKEEPING}
    brief["sections"] = [
        {k: v for k, v in s.items() if k not in _SECTION_BOOKKEEPING}
        for s in snap.get("sections") or []
    ]
    return json.dumps(brief, sort_keys=True, default=str)


def materialise(
    snap: Dict[str, Any], sources: List[Dict[str, Any]], with_run_sources=False
) -> Dict[str, Any]:
    """A full, renumbered brief from a snapshot and the brief's source list.

    ``with_run_sources`` rebuilds each current run's source records from its
    mapping (for a restore); a comparison only needs the text."""
    content = {k: copy.deepcopy(v) for k, v in snap.items() if k != "sections"}
    content["sources"] = list(sources)
    by_id = _sources_by_id(content)
    content["sections"] = []
    for section in snap.get("sections") or []:
        out = {k: copy.deepcopy(v) for k, v in section.items() if k != "run"}
        run = section.get("run")
        out["runs"] = []
        out["currentRunId"] = None
        if run:
            records = (
                _records_for(run.get("mapping") or {}, by_id)
                if with_run_sources
                else []
            )
            out["runs"] = [{**copy.deepcopy(run), "sources": records}]
            out["currentRunId"] = run["id"]
        content["sections"].append(out)
    return renumber(content)


# ---------------------------------------------------------------------------
# Describing a change
# ---------------------------------------------------------------------------


def summarise(kind: str, section_title: str = "", detail: str = "") -> str:
    """The Log's one-line description of a version of a given kind."""
    if kind in _SECTION_SUMMARIES:
        return _SECTION_SUMMARIES[kind].format(title=section_title or "Untitled")
    return _BRIEF_SUMMARIES[kind].format(detail=detail)


def _quoted(sections: List[Dict[str, Any]]) -> str:
    """“Title” for one section, "3 sections" for more."""
    if len(sections) == 1:
        return f"“{sections[0].get('title') or 'Untitled'}”"
    return f"{len(sections)} sections"


def settings_phrases(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> List[str]:
    """The brief-wide settings that differ between two snapshots."""
    if old is None:
        return []
    phrases: List[str] = []
    for key in sorted(set(old) | set(new)):
        if key in _BRIEF_BOOKKEEPING or key in ("sections", "activityId", "id"):
            continue
        if old.get(key) != new.get(key):
            phrase = _SETTING_PHRASES.get(key, "Changed the brief settings")
            if key == "title":
                phrase = f"Renamed the brief to “{new.get('title') or ''}”"
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases


def _run_id(section: Dict[str, Any]) -> Optional[str]:
    return (section.get("run") or {}).get("id")


def _moved(old: Dict[str, Dict[str, Any]], common: List[Dict[str, Any]]) -> bool:
    """Whether the sections both snapshots share changed order or level."""
    order = [s["id"] for s in common]
    old_order = [sid for sid in old if sid in {s["id"] for s in common}]
    return order != old_order or any(
        s.get("level") != old[s["id"]].get("level") for s in common
    )


def _differs(old: Dict[str, Dict[str, Any]], keys) -> Any:
    """A filter: the shared sections whose ``keys`` differ from before."""
    return lambda s: any(s.get(k) != old[s["id"]].get(k) for k in keys)


def _section_phrases(
    old: Dict[str, Dict[str, Any]], new_sections: List[Dict[str, Any]]
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """(structure phrases, text phrases, sections touched) between two
    snapshots' sections."""
    new_ids = {s["id"] for s in new_sections}
    added = [s for s in new_sections if s["id"] not in old]
    removed = [s for sid, s in old.items() if sid not in new_ids]
    common = [s for s in new_sections if s["id"] in old]
    renamed = list(filter(_differs(old, ("title",)), common))
    retuned = list(filter(_differs(old, _SECTION_SETTING_KEYS), common))
    edited = [s for s in common if _run_id(s) != _run_id(old[s["id"]])]
    structure: List[str] = []
    if added:
        structure.append(f"Added {_quoted(added)}")
    if removed:
        structure.append(f"Removed {_quoted(removed)}")
    structure += [
        f"Renamed {_quoted([old[s['id']]])} to {_quoted([s])}" for s in renamed
    ]
    if _moved(old, common):
        structure.append("Reordered the headings")
    if retuned:
        structure.append(f"Changed the settings of {_quoted(retuned)}")
    text = [f"Edited {_quoted(edited)} by hand"] if edited else []
    return structure, text, added + removed + renamed + retuned + edited


def describe_change(
    old: Optional[Dict[str, Any]], new: Dict[str, Any]
) -> Tuple[str, Optional[str], str]:
    """``(kind, section_id, summary)`` for a save the browser made (a change
    of headings, settings or a section's text by hand) between two
    snapshots."""
    if old is None:
        return KIND_CREATED, None, summarise(KIND_CREATED)
    structure, text, touched = _section_phrases(
        {s["id"]: s for s in old.get("sections") or []}, new.get("sections") or []
    )
    settings = settings_phrases(old, new)
    ids = {s["id"] for s in touched}
    section_id = next(iter(ids)) if len(ids) == 1 else None
    if text and not structure and not settings and section_id:
        kind = "manual"
    elif structure or text:
        kind = KIND_STRUCTURE
    else:
        kind = KIND_SETTINGS
    phrases = structure + text + settings
    return kind, section_id, "; ".join(phrases) or "Changed the brief settings"


# ---------------------------------------------------------------------------
# Comparing two versions
# ---------------------------------------------------------------------------


def _row(section: Dict[str, Any], change: str, before=None, after=None, title=None):
    return {
        "id": section["id"],
        "title": section.get("title") or "",
        "level": section.get("level") or 1,
        "change": change,
        "before": before,
        "after": after,
        "beforeTitle": title,
    }


def compare(
    previous: Optional[Dict[str, Any]], content: Dict[str, Any]
) -> Dict[str, Any]:
    """What changed from one full (renumbered) brief to the next, section by
    section in reading order, as the version Log shows it: each section's
    text as readers saw it before and after and whether it was added,
    removed, changed or left alone. A removed section is listed where it
    used to be."""
    old = {s["id"]: s for s in (previous or {}).get("sections") or []}
    rows: List[Dict[str, Any]] = []
    for section in content.get("sections") or []:
        after = section_display_text(section)
        prior = old.get(section["id"])
        if prior is None:
            rows.append(_row(section, "added", None, after))
            continue
        before = section_display_text(prior)
        same = (
            before == after
            and prior.get("title") == section.get("title")
            and prior.get("level") == section.get("level")
        )
        rows.append(
            _row(
                section,
                "unchanged" if same else "changed",
                before,
                after,
                prior.get("title"),
            )
        )
    ids = [row["id"] for row in rows]
    for position, (section_id, prior) in enumerate(old.items()):
        if section_id in ids:
            continue
        earlier = [sid for sid in list(old)[:position] if sid in ids]
        at = ids.index(earlier[-1]) + 1 if earlier else 0
        rows.insert(at, _row(prior, "removed", section_display_text(prior), None))
        ids.insert(at, section_id)
    settings = (
        settings_phrases(snapshot(previous), snapshot(content)) if previous else []
    )
    return {"sections": rows, "settings": settings}


# ---------------------------------------------------------------------------
# Restoring a brief to a version
# ---------------------------------------------------------------------------


def _restored_section(
    target: Dict[str, Any], current: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """A section as the version had it, keeping the section's own history:
    its runs and Log stay, and the version's run becomes current."""
    out = {
        key: copy.deepcopy(value)
        for key, value in target.items()
        if key not in ("runs", "renumbered", "audit", "currentRunId")
    }
    runs = copy.deepcopy((current or {}).get("runs") or target.get("runs") or [])
    audit = copy.deepcopy((current or target).get("audit") or [])
    run = current_run(target)
    for existing in runs:
        if existing.get("status") == RUN_CURRENT:
            existing["status"] = RUN_SUPERSEDED
    if run is not None:
        kept = find_run({"runs": runs}, run["id"])
        if kept is None:
            kept = {**copy.deepcopy(run), "sourcesRetained": SOURCES_EXACT}
            runs.append(kept)
        kept["status"] = RUN_CURRENT
    out["runs"] = runs
    out["audit"] = audit
    out["currentRunId"] = run["id"] if run else None
    out["status"] = "done" if run else "pending"
    return out


def _restore_entry(
    section: Dict[str, Any], before: str, number: int, stamp: int
) -> Dict[str, Any]:
    run = current_run(section)
    entry = {
        "id": f"a-v{number}-{stamp}",
        "kind": "restore",
        "at": stamp,
        "restoredFrom": {"version": number},
        "sourceCount": len((run or {}).get("sources") or []),
        "addedSourceCount": 0,
        "unresolvedCount": len((run or {}).get("unresolved") or []),
        "before": before,
    }
    if run is not None:
        entry["runId"] = run["id"]
    return entry


def restore_brief(
    content: Dict[str, Any],
    snap: Dict[str, Any],
    number: int,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """The brief restored to a version: its headings, settings and each
    section's text as they were then. Each section keeps its own history,
    and every section whose text changes gets a "Restored" row in its Log;
    nothing is deleted from the brief's sources."""
    require_current_format(content)
    stamp = _now_ms(now_ms)
    target = materialise(snap, content.get("sources") or [], with_run_sources=True)
    current = {s["id"]: s for s in content.get("sections") or []}
    before = {sid: section_display_text(s) for sid, s in current.items()}
    restored = copy.deepcopy(content)
    restored["sections"] = [
        _restored_section(section, current.get(section["id"]))
        for section in target["sections"]
    ]
    for key in RESTORED_SETTINGS:
        if key in snap:
            restored[key] = copy.deepcopy(snap[key])
        else:
            restored.pop(key, None)
    for section in restored["sections"]:
        apply_retention(section)
    renumber(restored, stamp)
    for section in restored["sections"]:
        prior = before.get(section["id"], "")
        if prior == section_display_text(section) and section["id"] in before:
            continue
        entry = _restore_entry(section, prior, number, stamp)
        section["audit"].append(entry)
        complete_entry(section, entry)
    check_size(restored)
    return restored
