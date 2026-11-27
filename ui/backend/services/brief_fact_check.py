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
from types import SimpleNamespace
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
from ui.backend.services.brief_claim_records import (
    checked_pairs,
    claim_passages,
    uses_claim_records,
)
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


class FactCheckError(BriefCitationError):
    """A check that does not describe the brief version it names."""


# ---------------------------------------------------------------------------
# Matching a check to a brief
# ---------------------------------------------------------------------------

# A judged passage: the section it sits in, the passage, the judge's row.
JudgedPassage = Tuple[Optional[str], CitedPassage, Any]


def current_passages(
    content: Dict[str, Any],
    include_uncited: bool = False,
) -> List[Tuple[Optional[str], CitedPassage]]:
    """The brief's cited passages in order, each with the id of its section:
    the same passages, in the same order, as a check judges them."""
    out: List[Tuple[Optional[str], CitedPassage]] = []
    for section in researched_sections(content):
        for passage in extract_cited_passages(section, include_uncited):
            out.append((section.get("id"), passage))
    return out


def judged_passages(
    content: Dict[str, Any],
    check_passages: Sequence[Any],
    include_uncited: bool = False,
) -> Optional[List[JudgedPassage]]:
    """The check's rows placed in the sections of ``content``, the brief as
    the check judged it, or ``None`` when ``content`` is not what the check
    judged (a passage edited, added or removed)."""
    passages = current_passages(content, include_uncited)
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


def _same_evidence(current, checked):
    # Display numbers can move when a different section is edited. The
    # stored passage IDs, excerpts and unresolved references identify what
    # the judge actually inspected.
    def identity(passage):
        return {
            (
                s.get("sourceId"),
                s.get("chunkId"),
                s.get("docId"),
                s.get("text"),
                tuple(s.get("headings") or []),
                s.get("title"),
            )
            for s in passage.sources
        }

    return (
        identity(current) == identity(checked)
        and current.missing_indices == checked.missing_indices
    )


def coverage(
    content: Dict[str, Any],
    judged: Sequence[JudgedPassage],
    include_uncited: bool = False,
) -> Coverage:
    """Compare the brief as it is with what a check judged, section by
    section. A section is covered when its cited passages are the judged
    passages of that section, in order; a section with no cited passages has
    nothing to cover and is neither covered nor changed."""
    by_section: Dict[Optional[str], List[Tuple[CitedPassage, Any]]] = {}
    for section_id, passage, row in judged:
        by_section.setdefault(section_id, []).append((passage, row))
    out = Coverage()
    for section in researched_sections(content):
        section_id = section.get("id")
        passages = extract_cited_passages(section, include_uncited)
        if not passages:
            continue
        was = by_section.get(section_id, [])
        if len(passages) == len(was) and all(
            p.passage_clean == previous.passage_clean
            and (not include_uncited or _same_evidence(p, previous))
            for p, (previous, _) in zip(passages, was)
        ):
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
        await session.refresh(
            check,
            attribute_names=[
                "section_results" if uses_claim_records(check) else "passages"
            ],
        )
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


def fact_check_marks(cov: Coverage) -> List[Dict[str, Any]]:
    """The passages to highlight: every judged passage of a covered section,
    whatever its verdict, with the judge's reasoning. The passage is given
    as it reads on screen: the check stores the sentence with its markdown
    (a bold claim keeps its ``**``), while the document searches rendered
    text, which has none of it."""
    marks: List[Dict[str, Any]] = []
    for section_id, pairs in cov.covered.items():
        for passage, row in pairs:
            marks.append(
                {
                    "passage_id": row.passage_id,
                    "claim_id": row.id if getattr(row, "claim_number", None) else None,
                    "section_id": section_id,
                    "section_title": passage.section_title,
                    "passage": strip_inline_markdown(row.passage),
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


def legend(marks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every verdict with its label and how many highlighted passages carry
    it, in the judge's order, so the document can explain its colours."""
    counts: Dict[str, int] = {}
    for mark in marks:
        counts[mark["verdict"]] = counts.get(mark["verdict"], 0) + 1
    return [
        {"verdict": v, "label": VERDICT_LABELS[v], "count": counts.get(v, 0)}
        for v in JUDGE_VERDICTS
    ]


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


async def _checked_passages(session, brief, check, include_uncited):
    if uses_claim_records(check):
        return await run_in_threadpool(checked_pairs, check)
    judged = await judged_content(session, brief, check)
    if judged is None:
        # Before versions were linked: the check applies to the whole brief
        # as it is, or not at all.
        pairs = (
            judged_passages(brief.content or {}, check.passages, include_uncited) or []
        )
    else:
        matched = judged_passages(judged, check.passages, include_uncited)
        if matched is None:
            raise FactCheckError(
                f"Citation check {check.id} does not match brief version "
                f"{check.brief_version_number}"
            )
        pairs = matched
    return pairs


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
    include_uncited = getattr(check, "check_kind", None) == "full"
    pairs = await _checked_passages(session, brief, check, include_uncited)
    cov = await run_in_threadpool(coverage, content, pairs, include_uncited)
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
        match = locate_quote(quote.get("quote") or "", [excerpt])
        if match["status"] == "missing":
            continue
        for span in match["spans"]:
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
        heading = source.get("section") or ""
        text = "\n".join(part for part in (heading, excerpt) if part)
        ranges = _quoted_ranges(text, source.get("index"), quotes)
        if heading and not any(start < len(heading) for start, _ in ranges):
            ranges = [(a - len(heading) - 1, b - len(heading) - 1) for a, b in ranges]
            text = excerpt
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
                "segments": excerpt_segments(text, ranges),
            }
        )
    return blocks


def _claim_row(check, passage_id):
    return next(
        (
            SimpleNamespace(**row)
            for _, _, row in claim_passages(check.section_results, passage_id)
        ),
        None,
    )


async def _legacy_evidence_row(session, brief, check_id, passage_id):
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
    check = await session.get(BriefCitationCheck, check_id)
    if check is None or check.brief_id != brief.id or check.status != CHECK_COMPLETED:
        return None
    if uses_claim_records(check):
        await session.refresh(check, ["section_results"])
        row = await run_in_threadpool(_claim_row, check, passage_id)
    else:
        row = await _legacy_evidence_row(session, brief, check_id, passage_id)
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
# Checks in the version Log
# ---------------------------------------------------------------------------


def check_label(check: Any) -> str:
    """How a version Log row names the check that judged it."""
    stats = check.summary_stats or {}
    if getattr(check, "check_kind", None) == "full":
        if counts := stats.get("section_counts"):
            return (
                f"Full Brief check: {counts['pass']} sections passed, "
                f"{counts['fail']} failed, {counts['error']} with errors"
            )
        return f"Full Brief check {check.status}"
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
