"""Present saved Brief checks, export their results, and dispatch new checks."""

import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

from sqlalchemy import update

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.testing_models import (
    CHECK_FAILED,
    CHECK_PENDING,
    CHECK_RUNNING,
    BriefCitationCheck,
)
from ui.backend.services.citation_fidelity import (
    FLAGGED_VERDICTS,
    JUDGE_VERDICTS,
    CitedPassage,
    extract_cited_passages,
    judgement_row,
    researched_sections,
    source_body,
    source_section,
    verify_quotes,
    write_review_workbook,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Passages and prompts (pure)
# ---------------------------------------------------------------------------


def brief_passages(content: Dict[str, Any]) -> List[CitedPassage]:
    """Every cited passage of the brief's researched sections, in order."""
    passages: List[CitedPassage] = []
    for section in researched_sections(content):
        passages.extend(extract_cited_passages(section))
    return passages


def count_cited_passages(content: Dict[str, Any]) -> int:
    return len(brief_passages(content))


def source_rows(passage: CitedPassage) -> List[Dict[str, Any]]:
    """The cited excerpts as stored on the passage row (for the detail view)."""
    return [
        {
            "index": src.get("index"),
            "title": src.get("title"),
            "page": src.get("page"),
            "doc_id": src.get("docId"),
            "chunk_id": src.get("chunkId"),
            "pdf_url": src.get("pdfUrl") or src.get("reportUrl"),
            "section": source_section(src),
            "excerpt": source_body(src),
            # Trace: the brief-wide source, the agent's own number(s) for it
            # in this section and the run that returned it.
            "source_id": src.get("sourceId"),
            "agent_indices": list(src.get("agentIndices") or []),
            "run_id": src.get("runId"),
        }
        for src in passage.sources
    ]


def passage_record(
    pid: int,
    passage: CitedPassage,
    judgement: Dict[str, Any],
    usage: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Column values for one ``brief_citation_check_passages`` row: the
    notebook's flat ``judgement_row`` plus structured fields for the UI."""
    flat = judgement_row(pid, passage, judgement)
    quotes = judgement.get("supporting_quotes") or []
    checks = verify_quotes(passage, quotes)
    usage = usage or {}
    return {
        "passage_id": pid,
        "brief_section": flat["brief_section"],
        "passage": flat["passage"],
        "citations": flat["citations"],
        "documents": flat["documents"],
        "sources": source_rows(passage),
        "dangling_citations": ", ".join(str(i) for i in passage.missing_indices),
        "verdict": flat["verdict"],
        "flagged": flat["flagged"],
        "confidence": flat["confidence"],
        "problems": list(judgement.get("problems") or []),
        "explanation": flat["explanation"],
        "supporting_quotes": [
            {**quote, "status": check["status"]} for quote, check in zip(quotes, checks)
        ],
        "quotes_verified": flat["quotes_verified"],
        "quote_not_in_source": flat["quote_not_in_source"],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "error_message": error,
    }


# ---------------------------------------------------------------------------
# Summary (pure)
# ---------------------------------------------------------------------------


def _section_row(section: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in JUDGE_VERDICTS}
    total = len(rows)
    return {
        "brief_section": section,
        **counts,
        "total": total,
        "flagged_share": round(1 - counts["supported"] / total, 2) if total else 0.0,
    }


def summarise(
    rows: List[Dict[str, Any]], duration_ms: int, judge_model: Optional[str]
) -> Dict[str, Any]:
    """The check's summary: verdict counts, flagged share, per-section rows
    (notebook cell 17), token totals and cost."""
    from ui.backend.utils.llm_costs import compute_cost

    sections: List[str] = []
    for row in rows:
        if row["brief_section"] not in sections:
            sections.append(row["brief_section"])
    by_section = [
        _section_row(s, [r for r in rows if r["brief_section"] == s]) for s in sections
    ]
    total = _section_row("TOTAL", rows)
    prompt = sum(int(r.get("prompt_tokens") or 0) for r in rows)
    completion = sum(int(r.get("completion_tokens") or 0) for r in rows)
    cost = (
        compute_cost(judge_model, prompt, completion) if prompt or completion else None
    )
    return {
        "total": len(rows),
        "verdicts": {v: total[v] for v in JUDGE_VERDICTS},
        "flagged": sum(1 for r in rows if r["flagged"]),
        "flagged_share": total["flagged_share"],
        "quote_not_in_source": sum(1 for r in rows if r["quote_not_in_source"]),
        "not_judged": sum(1 for r in rows if r.get("error_message")),
        "by_section": by_section,
        "duration_ms": duration_ms,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost_usd": round(float(cost), 6) if cost is not None else None,
    }


# Column order of the workbook sheets (the notebook's ``judgement_row``).
_SHEET_COLUMNS = (
    "passage_id",
    "brief_section",
    "passage",
    "citations",
    "documents",
    "verdict",
    "flagged",
    "confidence",
    "problems",
    "explanation",
    "supporting_quotes",
    "quotes_verified",
    "quote_not_in_source",
    "dangling_citations",
    "error_message",
)


def _sheet_row(record: Dict[str, Any]) -> Dict[str, Any]:
    row = {column: record.get(column) for column in _SHEET_COLUMNS}
    if record.get("claim_number") is not None:
        row.update(
            claim_id=str(record["id"]),
            section_id=record["section_id"],
            claim_number=record["claim_number"],
            outcome=record["outcome"],
            score=record["score"],
            passed=record["passed"],
        )
    row["problems"] = "\n".join(record.get("problems") or [])
    row["supporting_quotes"] = "\n".join(
        f"[{q.get('citation')}] {q.get('quote')} ({q.get('status')})"
        for q in record.get("supporting_quotes") or []
    )
    return row


def build_review_workbook(
    passages: List[Dict[str, Any]], by_section: List[Dict[str, Any]], sections=None
) -> bytes:
    """The notebook's review workbook — Flagged / All judgements / Summary —
    from stored passage rows and the check's per-section summary."""
    rows = [_sheet_row(p) for p in sorted(passages, key=lambda p: p["passage_id"])]
    severity = {"unsupported": 0, "cannot_assess": 1, "partially_supported": 2}
    flagged = sorted(
        (r for r in rows if r["flagged"]),
        key=lambda r: (severity.get(r["verdict"], 3), -(r["confidence"] or 0.0)),
    )
    buffer = BytesIO()
    sheets = {"Flagged": flagged, "All judgements": rows, "Summary": by_section}
    if sections is not None:
        sheets["Section checks"] = [
            {
                "section": section["heading"],
                "number": section["number"],
                "expectation": check.get("label") or check["type"],
                "passed": check.get("passed"),
                "score": check.get("score"),
                "assessment": check.get("message"),
            }
            for section in sections
            for check in section["assertion_results"]
        ]
    write_review_workbook(sheets, buffer)
    return buffer.getvalue()


def resolve_judge_model(model_combo: Optional[str]) -> Optional[str]:
    """config.json's judge for a model combo: its ``judge_model``, else its
    summarisation model, else the default combo's, else the app default (same
    rule as experiments). A group's choice (Group Settings > LLMs) is applied
    by the caller and overrides this."""
    from ui.backend.services.llm_choice import JUDGE, combo_default, default_combo
    from ui.backend.services.test_runner import _default_summary_model, _resolve_combo

    combo = _resolve_combo(model_combo)
    return (
        combo.get("judge_model")
        or combo.get("summary_model")
        or combo_default(JUDGE, default_combo())
        or _default_summary_model()
    )


async def _record_check_usage(check: BriefCitationCheck) -> None:
    """Mirror the finished check's token totals into ``user_activity``
    (type ``evaluation``, one row keyed by the check id). Monitoring only:
    errors are logged and swallowed."""
    from decimal import Decimal

    from ui.backend.services.usage_recorder import record_llm_usage

    try:
        stats = check.summary_stats or {}
        cost = stats.get("cost_usd")
        await record_llm_usage(
            usage={
                "llm_model": check.judge_model,
                "prompt_tokens": stats.get("prompt_tokens"),
                "completion_tokens": stats.get("completion_tokens"),
            },
            activity_type="evaluation",
            query=f"Brief citation check: {check.brief_title}",
            user_id=check.created_by_user_id,
            search_id=check.id,
            server_owned=True,
            filters_extra={
                "check_id": str(check.id),
                "brief_id": str(check.brief_id),
                "data_source": check.data_source,
                "passages": stats.get("total"),
            },
            cost_usd=Decimal(str(cost)) if cost is not None else None,
        )
    except Exception:
        logger.warning("Failed to record brief check usage", exc_info=True)


async def _fail(session: Any, check: BriefCitationCheck, message: str) -> None:
    check.status = CHECK_FAILED
    check.finished_at = _utcnow()
    check.summary_stats = {"error": message}
    await session.commit()


async def run_check(
    check_id: uuid.UUID,
    session_factory: Any = None,
) -> None:
    factory = session_factory or async_session_factory
    async with factory() as session:
        check = await session.get(BriefCitationCheck, check_id)
        if check is None:
            logger.error("run_check: check %s not found", check_id)
            return
        if check.status != CHECK_PENDING:
            return
        if check.check_kind != "full":
            await _fail(
                session, check, "Start a new saved Brief check to assess this version."
            )
            return
        from ui.backend.services.saved_brief_check_runner import run_full_check

        try:
            await run_full_check(session, check)
        except Exception:
            logger.exception("Brief citation check %s failed unexpectedly", check_id)
            await _fail(session, check, "Check failed")


async def recover_orphaned_checks(session_factory: Any = None) -> None:
    """Fail checks still pending/running after an API restart (their
    background task did not survive), like ``recover_orphaned_runs``."""
    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            result = await session.execute(
                update(BriefCitationCheck)
                .where(BriefCitationCheck.status.in_([CHECK_RUNNING, CHECK_PENDING]))
                .values(
                    status=CHECK_FAILED,
                    finished_at=_utcnow(),
                    summary_stats={"error": "api restarted mid-check (orphaned task)"},
                )
            )
            await session.commit()
            recovered = getattr(result, "rowcount", 0) or 0
            if recovered:
                logger.info("Recovered %s orphaned brief citation check(s)", recovered)
    except Exception:
        logger.exception("Failed to recover orphaned brief citation checks")


__all__ = [
    "FLAGGED_VERDICTS",
    "brief_passages",
    "build_review_workbook",
    "count_cited_passages",
    "passage_record",
    "recover_orphaned_checks",
    "resolve_judge_model",
    "run_check",
    "summarise",
]
