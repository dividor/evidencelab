"""Run a brief citation check: judge every cited passage of a saved brief.

The Evaluation Harness "Brief" type. For each passage of the brief that
carries ``[n]`` markers, the LLM judge sees the passage and the exact source
excerpts it cites, and answers with a verdict; its supporting quotes are then
checked mechanically against those excerpts (``citation_fidelity``). One
passage row is committed at a time so the UI can show progress, and the
check's token usage is mirrored into ``user_activity`` like an experiment run.

The judge runs through ``utils.llm_factory.get_llm`` so any configured
provider works and every call is cost-tracked. Prompts live in
``prompts/citation_judge_*.j2``.

Several api copies may share the database (every cloud layout runs two or
more). The runner therefore owns its row only while the row still says
``running``: every write is conditional on that status, so a check that was
cancelled, or failed as orphaned by another copy, keeps that record and the
runner stops. See ``job_liveness`` for how an orphaned check is recognised.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.models import Brief
from ui.backend.auth.testing_models import (
    CHECK_COMPLETED,
    CHECK_FAILED,
    CHECK_PENDING,
    CHECK_RUNNING,
    BriefCitationCheck,
    BriefCitationCheckPassage,
)
from ui.backend.services.citation_fidelity import (
    FLAGGED_VERDICTS,
    JUDGE_VERDICTS,
    CitedPassage,
    count_reference_lines,
    extract_cited_passages,
    format_excerpts,
    judgement_row,
    parse_judge_response,
    researched_sections,
    source_body,
    source_section,
    verify_quotes,
    write_review_workbook,
)
from ui.backend.services.job_liveness import (
    is_stale,
    orphan_message,
    progress_stats,
    utcnow,
    write_while,
)

logger = logging.getLogger(__name__)

# Parallel judge requests, as in the notebook.
JUDGE_CONCURRENCY = 6
JUDGE_MAX_OUTPUT_TOKENS = 900

# Prompts are plain text for a model, not HTML: escaping would alter the
# excerpts the judge must quote character for character.
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_prompt_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",)),
)

# (verdict, confidence, quotes, problems, explanation) for a passage that
# could not be judged, mirroring the notebook's placeholders.
_NOT_JUDGED = {
    "verdict": "cannot_assess",
    "confidence": 0.0,
    "supporting_quotes": [],
}

_ACTIVE = (CHECK_RUNNING, CHECK_PENDING)

# Async judge: (system prompt, user prompt) -> (raw reply, usage payload).
JudgeFn = Callable[[str, str], Awaitable[Tuple[str, Dict[str, Any]]]]


def _utcnow() -> datetime:
    return utcnow()


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


def count_skipped_reference_lines(content: Dict[str, Any]) -> int:
    """Reference-list lines in the researched sections that the check leaves
    out (``citation_fidelity.count_reference_lines``)."""
    return sum(
        count_reference_lines(section.get("content") or "")
        for section in researched_sections(content)
    )


def judge_prompts(passage: CitedPassage) -> Tuple[str, str]:
    """(system, user) prompts for one passage, from the .j2 templates."""
    system = _prompt_env.get_template("citation_judge_system.j2").render()
    user = _prompt_env.get_template("citation_judge_user.j2").render(
        brief_section=passage.section_title,
        passage=passage.passage_clean,
        citations=", ".join(f"[{i}]" for i in passage.citation_indices),
        excerpts=format_excerpts(passage),
    )
    return system.strip(), user.strip()


def _dangling_problem(passage: CitedPassage) -> str:
    numbers = ", ".join(f"[{i}]" for i in passage.missing_indices)
    return f"Dangling citation(s) {numbers}: no source stored for these numbers."


def not_judged(passage: CitedPassage, reason: str) -> Dict[str, Any]:
    """Placeholder judgement for a passage the judge did not (or could not)
    assess, so it still appears in the table as ``cannot_assess``."""
    problems = [reason]
    if passage.missing_indices:
        problems.append(_dangling_problem(passage))
    return {
        **_NOT_JUDGED,
        "problems": problems,
        "explanation": "Not judged: " + reason,
    }


def judgement_or_error(passage: CitedPassage, raw: str) -> Dict[str, Any]:
    """Parse the judge reply; a malformed reply becomes a visible error row
    rather than a silent verdict (as the notebook does)."""
    try:
        judgement = parse_judge_response(raw)
    except ValueError as exc:
        return not_judged(passage, f"JUDGE ERROR: {exc}")
    if passage.missing_indices:
        judgement["problems"].append(_dangling_problem(passage))
    return judgement


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
    rows: List[Dict[str, Any]],
    duration_ms: int,
    judge_model: Optional[str],
    reference_lines_skipped: int = 0,
) -> Dict[str, Any]:
    """The check's summary: verdict counts, flagged share, per-section rows
    (notebook cell 17), token totals, cost and the reference-list lines the
    check left out."""
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
        "reference_lines_skipped": reference_lines_skipped,
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
    row["problems"] = "\n".join(record.get("problems") or [])
    row["supporting_quotes"] = "\n".join(
        f"[{q.get('citation')}] {q.get('quote')} ({q.get('status')})"
        for q in record.get("supporting_quotes") or []
    )
    return row


def build_review_workbook(
    passages: List[Dict[str, Any]], by_section: List[Dict[str, Any]]
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
    write_review_workbook(
        {"Flagged": flagged, "All judgements": rows, "Summary": by_section}, buffer
    )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Judge call
# ---------------------------------------------------------------------------


async def llm_judge(
    system_prompt: str, user_prompt: str, model_key: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """Raw judge completion via the app's model factory, cost-tracked."""
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.runnables import RunnableConfig

    from ui.backend.services.llm_service import summarize_usage_metadata
    from utils.llm_factory import get_llm, message_text

    llm = get_llm(model=model_key, temperature=0.0, max_tokens=JUDGE_MAX_OUTPUT_TOKENS)
    usage_handler = UsageMetadataCallbackHandler()
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        config=RunnableConfig(callbacks=[usage_handler]),
    )
    return message_text(response), summarize_usage_metadata(usage_handler, model_key)


def make_judge(model_key: Optional[str]) -> JudgeFn:
    async def judge(system_prompt: str, user_prompt: str) -> Tuple[str, Dict[str, Any]]:
        return await llm_judge(system_prompt, user_prompt, model_key)

    return judge


async def judge_passage(
    pid: int, passage: CitedPassage, judge: JudgeFn, semaphore: asyncio.Semaphore
) -> Dict[str, Any]:
    """Judge one passage; never raises — a failed call becomes an error row."""
    if not passage.sources:
        reason = "No source stored for citation(s) " + ", ".join(
            f"[{i}]" for i in passage.missing_indices
        )
        return passage_record(pid, passage, not_judged(passage, reason), error=reason)
    system_prompt, user_prompt = judge_prompts(passage)
    try:
        async with semaphore:
            raw, usage = await judge(system_prompt, user_prompt)
    except Exception as exc:
        logger.warning("Judge call failed for passage %s: %s", pid, exc, exc_info=True)
        reason = "JUDGE ERROR: the model call failed"
        return passage_record(pid, passage, not_judged(passage, reason), error=reason)
    judgement = judgement_or_error(passage, raw)
    error = next(
        (p for p in judgement["problems"] if p.startswith("JUDGE ERROR")), None
    )
    return passage_record(pid, passage, judgement, usage, error)


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------


def resolve_judge_model(model_combo: Optional[str]) -> Optional[str]:
    """The combo's summarisation model, else the app default (same rule as
    experiments)."""
    from ui.backend.services.test_runner import _default_summary_model, _resolve_combo

    return _resolve_combo(model_combo).get("summary_model") or _default_summary_model()


async def _record_check_usage(check: BriefCitationCheck, stats: Dict[str, Any]) -> None:
    """Mirror the finished check's token totals into ``user_activity``
    (type ``evaluation``, one row keyed by the check id). Monitoring only:
    errors are logged and swallowed."""
    from decimal import Decimal

    from ui.backend.services.usage_recorder import record_llm_usage

    try:
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


async def _write_while(
    session: Any, check_id: uuid.UUID, statuses: Tuple[str, ...], **values: Any
) -> bool:
    return await write_while(session, BriefCitationCheck, check_id, statuses, **values)


async def _fail(session: Any, check_id: uuid.UUID, message: str) -> None:
    """Fail a check this runner still owns. A failed flush may have left the
    session in a dead transaction, so roll back before writing."""
    await session.rollback()
    await _write_while(
        session,
        check_id,
        _ACTIVE,
        status=CHECK_FAILED,
        finished_at=_utcnow(),
        summary_stats={"error": message},
    )


async def _execute(
    session: Any, check: BriefCitationCheck, judge: JudgeFn, concurrency: int
) -> None:
    started = time.time()
    # A rolled-back write expires the row's attributes, so keep what the loop
    # needs in locals and never read ``check`` after a write that failed.
    check_id = check.id
    brief = await session.get(Brief, check.brief_id)
    if brief is None:
        await _fail(session, check_id, "Brief not found")
        return
    content = brief.content or {}
    passages = brief_passages(content)
    total = len(passages)
    # The row is ours only while it still says pending: a cancel, or orphan
    # recovery on another api copy, may have failed it meanwhile.
    claimed = await _write_while(
        session,
        check_id,
        (CHECK_PENDING,),
        status=CHECK_RUNNING,
        started_at=_utcnow(),
        summary_stats=progress_stats(0, total),
    )
    if not claimed:
        logger.info("Brief citation check %s is no longer pending; not run", check_id)
        return

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        asyncio.ensure_future(judge_passage(pid, p, judge, semaphore))
        for pid, p in enumerate(passages, start=1)
    ]
    rows: List[Dict[str, Any]] = []
    for completed, task in enumerate(asyncio.as_completed(tasks), start=1):
        record = await task
        rows.append(record)
        session.add(BriefCitationCheckPassage(check_id=check_id, **record))
        if not await _write_while(
            session,
            check_id,
            (CHECK_RUNNING,),
            summary_stats=progress_stats(completed, total),
        ):
            logger.info(
                "Brief citation check %s was stopped by another writer", check_id
            )
            for pending in tasks:
                pending.cancel()
            return

    rows.sort(key=lambda r: r["passage_id"])
    stats = summarise(
        rows,
        int((time.time() - started) * 1000),
        check.judge_model,
        count_skipped_reference_lines(content),
    )
    finished = await _write_while(
        session,
        check_id,
        (CHECK_RUNNING,),
        status=CHECK_COMPLETED,
        finished_at=_utcnow(),
        summary_stats=stats,
    )
    if finished:
        await _record_check_usage(check, stats)


async def run_check(
    check_id: uuid.UUID,
    session_factory: Any = None,
    judge: Optional[JudgeFn] = None,
    concurrency: int = JUDGE_CONCURRENCY,
) -> None:
    """Background entrypoint: execute one check. ``judge`` is injectable for
    tests; by default the check's stored judge model is used."""
    factory = session_factory or async_session_factory
    async with factory() as session:
        check = await session.get(BriefCitationCheck, check_id)
        if check is None:
            logger.error("run_check: check %s not found", check_id)
            return
        try:
            await _execute(
                session, check, judge or make_judge(check.judge_model), concurrency
            )
        except Exception:
            logger.exception("Brief citation check %s failed unexpectedly", check_id)
            await _fail(session, check_id, "Check failed")


async def fail_stale_checks(session: Any, now: Optional[datetime] = None) -> int:
    """Fail the pending/running checks that have shown no progress for
    ``job_liveness.STALE_AFTER``: their background task is gone (the api copy
    running it stopped). A check with a fresh heartbeat belongs to a live
    runner, possibly on another api copy, and is left alone. Returns how many
    were failed."""
    now = now or _utcnow()
    result = await session.execute(
        select(BriefCitationCheck).where(BriefCitationCheck.status.in_(list(_ACTIVE)))
    )
    stale = [
        check
        for check in result.scalars().all()
        if check.status in _ACTIVE
        and is_stale(check.summary_stats, check.started_at, check.created_at, now)
    ]
    for check in stale:
        check.status = CHECK_FAILED
        check.finished_at = now
        check.summary_stats = {
            "error": orphan_message(
                check.summary_stats, check.started_at, check.created_at, now
            )
        }
    if stale:
        await session.commit()
    return len(stale)


async def recover_orphaned_checks(session_factory: Any = None) -> None:
    """At api start, fail the checks whose task is gone (``fail_stale_checks``).
    Not every running check: another api copy may be running it."""
    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            recovered = await fail_stale_checks(session)
            if recovered:
                logger.info("Recovered %s orphaned brief citation check(s)", recovered)
    except Exception:
        logger.exception("Failed to recover orphaned brief citation checks")


__all__ = [
    "FLAGGED_VERDICTS",
    "brief_passages",
    "build_review_workbook",
    "count_cited_passages",
    "count_skipped_reference_lines",
    "fail_stale_checks",
    "judge_prompts",
    "passage_record",
    "progress_stats",
    "recover_orphaned_checks",
    "resolve_judge_model",
    "run_check",
    "summarise",
]
