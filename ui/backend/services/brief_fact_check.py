"""The Fact Checker of an open brief.

A completed citation check (``citation_check_runner``) judged every cited
passage of one *version* of a brief: the check pins the brief's current
version when it starts (``BriefCitationCheck.brief_version_id``), and that
version is frozen from then on (see ``brief_version_store``). When a reader
opens the brief later, the judged version is rebuilt from the version Log and
compared with the brief section by section: a section whose cited passages
still read exactly as the judge saw them keeps its verdicts; a section
changed since is reported as not covered, so the reader is told rather than
shown stale highlights. The passages whose verdict the reader's group chose
to see (``briefFactCheckVerdicts`` in the group settings, "unsupported" by
default) are then highlighted in the document with the judge's explanation.

Checks made before versions were linked carry no version; they apply only
while the whole brief still reads as they judged it.

Everything the document shows is computed here: which check applies, which
sections it still covers, which passages to highlight with which label, and
the notes that say how the brief has moved on. The browser only paints what
it is given.

Tests: ``tests/unit/test_brief_fact_check.py``.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.models import Brief, BriefVersion
from ui.backend.auth.testing_models import CHECK_COMPLETED, BriefCitationCheck
from ui.backend.services import brief_version_store as store
from ui.backend.services import brief_versions as bv
from ui.backend.services.brief_citation_model import BriefCitationError
from ui.backend.services.citation_fidelity import (
    JUDGE_VERDICTS,
    CitedPassage,
    extract_cited_passages,
    researched_sections,
)

# The group setting: the verdicts the Fact Checker highlights.
FACT_CHECK_SETTING_KEY = "briefFactCheckVerdicts"
DEFAULT_HIGHLIGHT_VERDICTS = ["unsupported"]

# How a verdict reads in the document.
VERDICT_LABELS = {
    "supported": "Supported",
    "partially_supported": "Partially supported",
    "unsupported": "Unsupported",
    "cannot_assess": "Cannot assess",
}


class FactCheckError(BriefCitationError):
    """A check that does not describe the brief version it names."""


def validate_verdicts(values: Any) -> List[str]:
    """The verdict list a group setting may hold: known verdicts only, each
    once, in the order given. Raises ``ValueError`` otherwise."""
    if not isinstance(values, list):
        raise ValueError(f"{FACT_CHECK_SETTING_KEY} must be a list of verdicts")
    verdicts: List[str] = []
    for value in values:
        if value not in JUDGE_VERDICTS:
            raise ValueError(
                f"Unknown verdict {value!r}; expected one of {', '.join(JUDGE_VERDICTS)}"
            )
        if value not in verdicts:
            verdicts.append(value)
    return verdicts


def highlight_verdicts(settings: Optional[Dict[str, Any]]) -> List[str]:
    """The verdicts to highlight for a user, from their merged group settings;
    the default when no group set any."""
    raw = (settings or {}).get(FACT_CHECK_SETTING_KEY)
    if raw is None:
        return list(DEFAULT_HIGHLIGHT_VERDICTS)
    return validate_verdicts(raw)


# ---------------------------------------------------------------------------
# Matching a check to a brief
# ---------------------------------------------------------------------------

# A judged passage: the section it sits in, the passage, the judge's row.
JudgedPassage = Tuple[Optional[str], CitedPassage, Any]


def current_passages(
    content: Dict[str, Any],
) -> List[Tuple[Optional[str], CitedPassage]]:
    """The brief's cited passages in order, each with the id of its section:
    the same passages, in the same order, as a check judges them."""
    out: List[Tuple[Optional[str], CitedPassage]] = []
    for section in researched_sections(content):
        for passage in extract_cited_passages(section):
            out.append((section.get("id"), passage))
    return out


def judged_passages(
    content: Dict[str, Any], check_passages: Sequence[Any]
) -> Optional[List[JudgedPassage]]:
    """The check's rows placed in the sections of ``content``, the brief as
    the check judged it, or ``None`` when ``content`` is not what the check
    judged (a passage edited, added or removed)."""
    passages = current_passages(content)
    rows = sorted(check_passages, key=lambda r: r.passage_id)
    if len(rows) != len(passages):
        return None
    out: List[JudgedPassage] = []
    for row, (section_id, passage) in zip(rows, passages):
        if row.passage != passage.passage_clean:
            return None
        out.append((section_id, passage, row))
    return out


@dataclass
class Coverage:
    """Which of the brief's sections a check still describes."""

    # Section id -> the judged passages of a section whose cited passages
    # still read exactly as the judge saw them (the current passage and the
    # judge's row), in reading order.
    covered: Dict[str, List[Tuple[CitedPassage, Any]]] = field(default_factory=dict)
    # Sections with cited passages that changed since the check (or were
    # added), as ``{"id", "title"}`` in reading order: not highlighted.
    changed: List[Dict[str, str]] = field(default_factory=list)


def coverage(content: Dict[str, Any], judged: Sequence[JudgedPassage]) -> Coverage:
    """Compare the brief as it is with what a check judged, section by
    section. A section is covered when its cited passages are the judged
    passages of that section, in order; a section with no cited passages has
    nothing to cover and is neither covered nor changed."""
    by_section: Dict[Optional[str], List[Tuple[str, Any]]] = {}
    for section_id, passage, row in judged:
        by_section.setdefault(section_id, []).append((passage.passage_clean, row))
    out = Coverage()
    for section in researched_sections(content):
        section_id = section.get("id")
        passages = extract_cited_passages(section)
        if not passages:
            continue
        was = by_section.get(section_id, [])
        if [p.passage_clean for p in passages] == [text for text, _ in was]:
            out.covered[str(section_id)] = [
                (passage, row) for passage, (_, row) in zip(passages, was)
            ]
        else:
            out.changed.append(
                {"id": str(section_id), "title": section.get("title") or ""}
            )
    return out


async def latest_completed_check(
    session: AsyncSession, brief: Brief
) -> Optional[BriefCitationCheck]:
    """The brief's newest completed check, with its passages loaded."""
    check = (
        (
            await session.execute(
                select(BriefCitationCheck)
                .where(
                    BriefCitationCheck.brief_id == brief.id,
                    BriefCitationCheck.status == CHECK_COMPLETED,
                )
                .order_by(BriefCitationCheck.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if check is not None:
        await session.refresh(check, attribute_names=["passages"])
    return check


async def judged_content(
    session: AsyncSession, brief: Brief, check: BriefCitationCheck
) -> Optional[Dict[str, Any]]:
    """The brief as the check judged it: its pinned version, rebuilt with the
    brief's source list (a superset of every source the version names). None
    for a check made before versions were linked."""
    if check.brief_version_id is None:
        return None
    version = await session.get(BriefVersion, check.brief_version_id)
    if version is None:
        # The id is nulled when a version row goes, so a stored id resolves.
        raise FactCheckError(
            f"Citation check {check.id} names a brief version that does not exist"
        )
    sources = (brief.content or {}).get("sources") or []
    return await run_in_threadpool(bv.materialise, version.content, sources)


# ---------------------------------------------------------------------------
# What the document shows
# ---------------------------------------------------------------------------


def _citations(passage: CitedPassage) -> str:
    # The numbers readers see now, in the form the check stores them.
    return ", ".join(str(i) for i in passage.citation_indices)


def fact_check_marks(cov: Coverage, verdicts: Sequence[str]) -> List[Dict[str, Any]]:
    """The passages to highlight: every judged passage of a covered section
    whose verdict is in ``verdicts``, with the judge's reasoning."""
    marks: List[Dict[str, Any]] = []
    for section_id, pairs in cov.covered.items():
        for passage, row in pairs:
            if row.verdict not in verdicts:
                continue
            marks.append(
                {
                    "passage_id": row.passage_id,
                    "section_id": section_id,
                    "section_title": passage.section_title,
                    "passage": row.passage,
                    "verdict": row.verdict,
                    "verdict_label": VERDICT_LABELS.get(row.verdict, row.verdict),
                    "explanation": row.explanation,
                    "problems": list(row.problems or []),
                    "confidence": row.confidence,
                    "citations": _citations(passage),
                    "quote_not_in_source": row.quote_not_in_source,
                }
            )
    return marks


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def version_note(
    checked: Optional[int], current: Optional[int], changed: Sequence[Dict[str, str]]
) -> str:
    """One line on how the brief relates to the version the check judged,
    for the Fact Checker button."""
    if checked is None:
        return (
            "Checked before version history began; every cited passage still "
            "reads as it was judged."
        )
    if current is None or current == checked:
        return f"Checked at version {checked}, the brief's current version."
    head = f"Checked at version {checked}; the brief is now at version {current}"
    if not changed:
        return head + ", with its cited passages unchanged since."
    titles = ", ".join(f"“{s['title'] or 'Untitled'}”" for s in changed)
    return (
        f"{head}. {_plural(len(changed), 'section')} changed since and "
        f"{'is' if len(changed) == 1 else 'are'} not highlighted: {titles}."
    )


def section_note(checked: Optional[int]) -> str:
    """Shown above a section the check no longer covers."""
    at = f" (version {checked})" if checked is not None else ""
    return f"Changed since the citation check{at}; not covered by the Fact Checker."


def brief_changed(check: Any, current: Optional[int]) -> Optional[bool]:
    """Whether the brief has a newer version than the one a check judged;
    None for a check made before versions were linked."""
    if check.brief_version_number is None:
        return None
    return current != check.brief_version_number


def _nothing(current: Optional[int], verdicts: Sequence[str]) -> Dict[str, Any]:
    return {
        "check": None,
        "brief_version": None,
        "current_version": current,
        "highlight_verdicts": list(verdicts),
        "note": "",
        "changed_sections": [],
        "marks": [],
    }


async def fact_check(
    session: AsyncSession, brief: Brief, verdicts: Sequence[str]
) -> Dict[str, Any]:
    """The Fact Checker's answer for a brief: the check that applies (the
    newest completed one, while it still covers at least one section with
    cited passages), the brief's version numbers, the sections it no longer
    covers and the marks to paint."""
    current = (await store.latest_numbers(session, [brief.id])).get(brief.id)
    check = await latest_completed_check(session, brief)
    if check is None:
        return _nothing(current, verdicts)
    content = brief.content or {}
    judged = await judged_content(session, brief, check)
    if judged is None:
        # Before versions were linked: the check applies to the whole brief
        # as it is, or not at all.
        pairs = judged_passages(content, check.passages) or []
    else:
        matched = judged_passages(judged, check.passages)
        if matched is None:
            raise FactCheckError(
                f"Citation check {check.id} does not match brief version "
                f"{check.brief_version_number}"
            )
        pairs = matched
    cov = coverage(content, pairs)
    if not cov.covered:
        return _nothing(current, verdicts)
    checked = check.brief_version_number
    return {
        "check": check,
        "brief_version": checked,
        "current_version": current,
        "highlight_verdicts": list(verdicts),
        "note": version_note(checked, current, cov.changed),
        "changed_sections": [
            {**section, "note": section_note(checked)} for section in cov.changed
        ],
        "marks": fact_check_marks(cov, verdicts),
    }


# ---------------------------------------------------------------------------
# Checks in the version Log
# ---------------------------------------------------------------------------


def check_label(check: Any) -> str:
    """How a version Log row names the check that judged it."""
    stats = check.summary_stats or {}
    if check.status == CHECK_COMPLETED and "total" in stats:
        return (
            f"Citation check: {stats.get('flagged', 0)} of "
            f"{_plural(int(stats['total']), 'passage')} flagged"
        )
    return f"Citation check {check.status}"


async def checks_by_version(
    session: AsyncSession, brief_id: uuid.UUID
) -> Dict[uuid.UUID, BriefCitationCheck]:
    """The newest check of each version of a brief that was checked."""
    rows = (
        await session.execute(
            select(BriefCitationCheck)
            .where(
                BriefCitationCheck.brief_id == brief_id,
                BriefCitationCheck.brief_version_id.is_not(None),
            )
            .order_by(BriefCitationCheck.created_at.desc())
        )
    ).scalars()
    out: Dict[uuid.UUID, BriefCitationCheck] = {}
    for check in rows.all():
        if check.brief_version_id is not None:
            out.setdefault(check.brief_version_id, check)
    return out


def version_check(check: Optional[Any]) -> Optional[Dict[str, Any]]:
    """What a version Log row says about the check that judged it."""
    if check is None:
        return None
    stats = check.summary_stats or {}
    return {
        "id": check.id,
        "status": check.status,
        "created_at": check.created_at,
        "flagged": stats.get("flagged") if "total" in stats else None,
        "total": stats.get("total"),
        "label": check_label(check),
    }
