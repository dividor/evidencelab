"""The Fact Checker of an open brief.

A completed citation check (``citation_check_runner``) judged every cited
passage of a brief as it was at the time. When a reader opens the brief, the
check still applies only if the brief's cited passages are the same ones the
judge saw; then the passages whose verdict the reader's group chose to see
(``briefFactCheckVerdicts`` in the group settings, "unsupported" by default)
are highlighted in the document with the judge's explanation.

Everything the document shows is computed here: which check is current,
which passages to highlight, in which section, with which label. The browser
only paints the marks it is given.

Tests: ``tests/unit/test_brief_fact_check.py``.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.models import Brief
from ui.backend.auth.testing_models import CHECK_COMPLETED, BriefCitationCheck
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


def check_matches(
    passages: Sequence[Tuple[Optional[str], CitedPassage]],
    check_passages: Sequence[Any],
) -> bool:
    """True when the check judged exactly the brief's current cited passages:
    the same prose, in the same order. A passage edited, added or removed
    since the check makes it stale."""
    judged = [row.passage for row in sorted(check_passages, key=lambda r: r.passage_id)]
    return judged == [passage.passage_clean for _, passage in passages]


async def current_check(
    session: AsyncSession, brief: Brief
) -> Optional[BriefCitationCheck]:
    """The newest completed check of the brief that judged its current cited
    passages, with its passages loaded, or ``None``."""
    passages = current_passages(brief.content or {})
    if not passages:
        return None
    rows = (
        await session.execute(
            select(BriefCitationCheck)
            .where(
                BriefCitationCheck.brief_id == brief.id,
                BriefCitationCheck.status == CHECK_COMPLETED,
            )
            .order_by(BriefCitationCheck.created_at.desc())
        )
    ).scalars()
    for check in rows:
        await session.refresh(check, attribute_names=["passages"])
        if check_matches(passages, check.passages):
            return check
    return None


def fact_check_marks(
    content: Dict[str, Any], check: BriefCitationCheck, verdicts: Sequence[str]
) -> List[Dict[str, Any]]:
    """The passages to highlight: every judged passage whose verdict is in
    ``verdicts``, placed in its section, with the judge's reasoning."""
    passages = current_passages(content)
    rows = sorted(check.passages, key=lambda r: r.passage_id)
    marks: List[Dict[str, Any]] = []
    for row, (section_id, passage) in zip(rows, passages):
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
                "citations": row.citations,
                "quote_not_in_source": row.quote_not_in_source,
            }
        )
    return marks
