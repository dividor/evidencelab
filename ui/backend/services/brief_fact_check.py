"""The Fact Checker of an open brief.

A completed citation check (``citation_check_runner``) judged every cited
passage of one *version* of a brief: the check pins the brief's current
version when it starts (``BriefCitationCheck.brief_version_id``), and that
version is frozen from then on (see ``brief_version_store``). When a reader
opens the brief later, the judged version is rebuilt from the version Log and
compared with the brief section by section: a section whose cited passages
still read exactly as the judge saw them keeps its verdicts; a section
changed since is reported as not covered, so the reader is told rather than
shown stale highlights. Every judged passage of a covered section is then
highlighted in the document in the colour of its verdict, with the judge's
explanation and the cited excerpts (the parts the judge quoted marked) a
pointer away.

A person may overrule the judge on a passage: the brief's owner or an
administrator accepts its citation, with an optional comment. The verdict is
kept; the acceptance is recorded beside it on the passage row, the passage is
painted in its own colour from then on, and the Testing (Brief) table lists
who accepted it and why. An acceptance belongs to the check that judged the
passage and can be withdrawn.

Checks made before versions were linked carry no version; they apply only
while the whole brief still reads as they judged it.

Everything the document shows is computed here: which check applies, which
sections it still covers, which passages to highlight with which label, the
legend's counts, the notes that say how the brief has moved on, and where in
each excerpt the judge's quotes sit. The browser only paints what it is given.

Tests: ``tests/unit/test_brief_fact_check.py``.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.models import Brief, BriefVersion
from ui.backend.auth.testing_models import (
    CHECK_COMPLETED,
    BriefCitationCheck,
    BriefCitationCheckPassage,
)
from ui.backend.services import brief_version_store as store
from ui.backend.services import brief_versions as bv
from ui.backend.services.brief_citation_model import BriefCitationError
from ui.backend.services.brief_sharing import owner_name
from ui.backend.services.citation_fidelity import (
    JUDGE_VERDICTS,
    CitedPassage,
    extract_cited_passages,
    locate_quote,
    researched_sections,
    strip_inline_markdown,
)

# How a verdict reads in the document.
VERDICT_LABELS = {
    "supported": "Supported",
    "partially_supported": "Partially supported",
    "unsupported": "Unsupported",
    "cannot_assess": "Cannot assess",
}

# The colour of a passage a person accepted, and how the legend names it.
ACCEPTED = "accepted"
ACCEPTED_LABEL = "Human accepted"


class FactCheckError(BriefCitationError):
    """A check that does not describe the brief version it names."""


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


def is_accepted(row: Any) -> bool:
    """Whether a person accepted the citation of a judged passage."""
    return row.human_accepted_at is not None


def accepted_label(row: Any) -> str:
    """Who accepted a passage and when, as the document says it; empty for
    a passage nobody accepted."""
    at = row.human_accepted_at
    if at is None:
        return ""
    day = at.astimezone(timezone.utc)
    who = row.human_accepted_by_name or "a deleted account"
    return f"Accepted by {who} on {day.day} {day:%B %Y}"


def fact_check_marks(cov: Coverage) -> List[Dict[str, Any]]:
    """The passages to highlight: every judged passage of a covered section,
    whatever its verdict, with the judge's reasoning and, once a person
    accepted its citation, who did and what they wrote. The passage is given
    as it reads on screen: the check stores the sentence with its markdown
    (a bold claim keeps its ``**``), while the document searches rendered
    text, which has none of it."""
    marks: List[Dict[str, Any]] = []
    for section_id, pairs in cov.covered.items():
        for passage, row in pairs:
            verdict_label = VERDICT_LABELS.get(row.verdict, row.verdict)
            accepted = is_accepted(row)
            marks.append(
                {
                    "passage_id": row.passage_id,
                    "section_id": section_id,
                    "section_title": passage.section_title,
                    "passage": strip_inline_markdown(row.passage),
                    "verdict": row.verdict,
                    "verdict_label": verdict_label,
                    "explanation": row.explanation,
                    "problems": list(row.problems or []),
                    "confidence": row.confidence,
                    "citations": _citations(passage),
                    "quote_not_in_source": row.quote_not_in_source,
                    "highlight": ACCEPTED if accepted else row.verdict,
                    "highlight_label": ACCEPTED_LABEL if accepted else verdict_label,
                    "accepted": accepted,
                    "accepted_label": accepted_label(row),
                    "accepted_comment": row.human_acceptance_comment or "",
                }
            )
    return marks


def legend(marks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every colour with its label and how many passages are painted in it,
    so the document can explain them: the verdicts in the judge's order
    (counting the passages nobody accepted), then the accepted ones."""
    counts: Dict[str, int] = {}
    for mark in marks:
        counts[mark["highlight"]] = counts.get(mark["highlight"], 0) + 1
    items = [
        {"verdict": v, "label": VERDICT_LABELS[v], "count": counts.get(v, 0)}
        for v in JUDGE_VERDICTS
    ]
    items.append(
        {"verdict": ACCEPTED, "label": ACCEPTED_LABEL, "count": counts.get(ACCEPTED, 0)}
    )
    return items


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


def _nothing(current: Optional[int]) -> Dict[str, Any]:
    return {
        "check": None,
        "brief_version": None,
        "current_version": current,
        "note": "",
        "changed_sections": [],
        "legend": legend([]),
        "marks": [],
    }


async def fact_check(session: AsyncSession, brief: Brief) -> Dict[str, Any]:
    """The Fact Checker's answer for a brief: the check that applies (the
    newest completed one, while it still covers at least one section with
    cited passages), the brief's version numbers, the sections it no longer
    covers, the marks to paint and the legend that explains their colours."""
    current = (await store.latest_numbers(session, [brief.id])).get(brief.id)
    check = await latest_completed_check(session, brief)
    if check is None:
        return _nothing(current)
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
        return _nothing(current)
    checked = check.brief_version_number
    marks = fact_check_marks(cov)
    return {
        "check": check,
        "brief_version": checked,
        "current_version": current,
        "note": version_note(checked, current, cov.changed),
        "changed_sections": [
            {**section, "note": section_note(checked)} for section in cov.changed
        ],
        "legend": legend(marks),
        "marks": marks,
    }


# ---------------------------------------------------------------------------
# Evidence: the cited excerpts with the judge's quotes marked
# ---------------------------------------------------------------------------

# A highlighted or plain run of an excerpt.
Segment = Dict[str, Any]


def _span_range(span: str, text: str) -> Optional[Tuple[int, int]]:
    """Where ``span`` sits in ``text``: ``locate_quote`` returns the matched
    words joined by single spaces, while the excerpt keeps its own
    whitespace, so the words are searched with any whitespace between."""
    words = span.split()
    if not words:
        return None
    found = re.search(r"\s+".join(re.escape(word) for word in words), text)
    return (found.start(), found.end()) if found else None


def _merged(ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def excerpt_segments(text: str, ranges: Sequence[Tuple[int, int]]) -> List[Segment]:
    """``text`` cut into runs, each highlighted or not, by the character
    ranges to highlight (overlaps merged); never an empty run."""
    segments: List[Segment] = []
    at = 0
    for start, end in _merged(ranges):
        if start > at:
            segments.append({"text": text[at:start], "highlighted": False})
        segments.append({"text": text[start:end], "highlighted": True})
        at = end
    if at < len(text):
        segments.append({"text": text[at:], "highlighted": False})
    return segments


def _quoted_ranges(
    excerpt: str, citation: Any, quotes: Sequence[Dict[str, Any]]
) -> List[Tuple[int, int]]:
    """The parts of one excerpt the judge quoted: each quote the judge
    attributed to this citation (or to none) is located in it afresh, as
    the check verified it, and the matched text is highlighted."""
    ranges: List[Tuple[int, int]] = []
    for quote in quotes:
        if quote.get("citation") not in (None, citation):
            continue
        for span in locate_quote(quote.get("quote") or "", [excerpt])["spans"]:
            found = _span_range(span, excerpt)
            if found:
                ranges.append(found)
    return ranges


def passage_evidence(row: Any) -> List[Dict[str, Any]]:
    """What the judge read for one passage: one block per cited source (as
    the check stored it), its excerpt cut into plain and highlighted runs,
    the highlighted ones being what the judge quoted from it."""
    quotes = list(row.supporting_quotes or [])
    blocks: List[Dict[str, Any]] = []
    for source in row.sources or []:
        excerpt = (source.get("excerpt") or "").strip()
        ranges = _quoted_ranges(excerpt, source.get("index"), quotes)
        page = source.get("page")
        title = source.get("title") or "Untitled"
        blocks.append(
            {
                "citation": source.get("index"),
                "label": f"[{source.get('index')}] {title}"
                + (f", p. {page}" if page is not None else ""),
                "title": title,
                "page": page,
                "section": source.get("section") or "",
                "doc_id": source.get("doc_id"),
                "chunk_id": source.get("chunk_id"),
                "pdf_url": source.get("pdf_url"),
                "quoted": bool(ranges),
                "segments": excerpt_segments(excerpt, ranges),
            }
        )
    return blocks


async def judged_row(
    session: AsyncSession, brief: Brief, check_id: uuid.UUID, passage_id: int
) -> Optional[BriefCitationCheckPassage]:
    """One judged passage of a completed check of ``brief``, or None when
    the check or the passage is not one of its."""
    return (
        (
            await session.execute(
                select(BriefCitationCheckPassage)
                .join(BriefCitationCheck)
                .where(
                    BriefCitationCheck.id == check_id,
                    BriefCitationCheck.brief_id == brief.id,
                    BriefCitationCheck.status == CHECK_COMPLETED,
                    BriefCitationCheckPassage.passage_id == passage_id,
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def fact_check_evidence(
    session: AsyncSession, brief: Brief, check_id: uuid.UUID, passage_id: int
) -> Optional[Dict[str, Any]]:
    """The evidence behind one highlighted passage of a completed check of
    ``brief``, or None when the check or the passage is not one of its."""
    row = await judged_row(session, brief, check_id, passage_id)
    if row is None:
        return None
    # Locating quotes in long excerpts is pure CPU work: off the event loop.
    evidence = await run_in_threadpool(passage_evidence, row)
    return {
        "passage_id": row.passage_id,
        "verdict": row.verdict,
        "verdict_label": VERDICT_LABELS.get(row.verdict, row.verdict),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# A person's acceptance of a citation
# ---------------------------------------------------------------------------


def may_accept(brief: Brief, user: Any) -> bool:
    """Whether ``user`` may accept citations of ``brief`` or withdraw an
    acceptance: its owner and administrators. Someone the brief is only
    shared with reads it, acceptances included, and changes nothing."""
    return brief.user_id == user.id or bool(user.is_superuser)


def clean_comment(comment: Optional[str]) -> Optional[str]:
    """A comment as it is stored: trimmed, and None when nothing was said."""
    return (comment or "").strip() or None


async def accept_passage(
    session: AsyncSession,
    brief: Brief,
    check_id: uuid.UUID,
    passage_id: int,
    user: Any,
    comment: Optional[str],
) -> bool:
    """Record that ``user`` accepts the citation of one judged passage, with
    their comment; accepting again replaces who, when and the comment. False
    when the check or the passage is not one of the brief's."""
    row = await judged_row(session, brief, check_id, passage_id)
    if row is None:
        return False
    row.human_accepted_at = datetime.now(timezone.utc)
    row.human_accepted_by_user_id = user.id
    row.human_accepted_by_name = owner_name(user)
    row.human_acceptance_comment = clean_comment(comment)
    await session.commit()
    return True


async def withdraw_acceptance(
    session: AsyncSession, brief: Brief, check_id: uuid.UUID, passage_id: int
) -> bool:
    """Take back the acceptance of one judged passage, leaving the judge's
    verdict to stand alone again. False when the check or the passage is not
    one of the brief's."""
    row = await judged_row(session, brief, check_id, passage_id)
    if row is None:
        return False
    row.human_accepted_at = None
    row.human_accepted_by_user_id = None
    row.human_accepted_by_name = None
    row.human_acceptance_comment = None
    await session.commit()
    return True


def accepted_count(passages: Sequence[Any]) -> int:
    """How many of a check's passages a person accepted."""
    return sum(1 for row in passages if is_accepted(row))


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
