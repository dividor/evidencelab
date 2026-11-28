"""Grade a pinned Brief version and store one assessment for each claim."""

import time
from datetime import datetime, timezone

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.models import Brief, BriefVersion
from ui.backend.auth.testing_models import BriefCitationCheck
from ui.backend.services import brief_versions
from ui.backend.services.brief_claim_records import bind_claims, claim_passages
from ui.backend.services.brief_score_metrics import saved_brief_scores
from ui.backend.services.evaluation_metrics import progress_stats
from ui.backend.services.saved_brief_evaluation import (
    grade_saved_section,
    section_inputs,
    section_result,
    version_profiles,
)


async def _has_status(session, check, expected):
    # Read the latest committed status and lock it until this section is saved.
    status = await session.scalar(
        select(BriefCitationCheck.status)
        .where(BriefCitationCheck.id == check.id)
        .with_for_update()
    )
    return status == expected


async def run_full_check(session, check):
    from ui.backend.services.citation_check_runner import _record_check_usage

    started = time.monotonic()
    brief = await session.get(Brief, check.brief_id)
    version = await session.get(BriefVersion, check.brief_version_id)
    if not brief or not version:
        raise ValueError("The pinned Brief version is unavailable.")
    content = await run_in_threadpool(
        brief_versions.materialise, version.content, brief.content.get("sources", [])
    )
    voices = await version_profiles(session, content, version.updated_at)
    inputs = await run_in_threadpool(lambda: list(section_inputs(content, voices)))
    if not inputs:
        raise ValueError("The Brief version has no sections.")
    if not await _has_status(session, check, "pending"):
        return
    total = len(inputs)
    check.status = "running"
    check.started_at = datetime.now(timezone.utc)
    outline = [
        dict(
            template=check.brief_title,
            heading=o["assignment"]["heading"],
            number=o["assignment"]["heading_number"],
        )
        for o, _, _ in inputs
    ]
    check.section_results = []
    check.summary_stats = progress_stats(0, total, outline)
    await session.commit()
    sections, usage = [], []
    offset = 0
    for position, (output, section_id, missing_voice) in enumerate(inputs):
        section_started = time.monotonic()
        checks = await grade_saved_section(
            output, position, missing_voice, check.judge_model
        )
        if not await _has_status(session, check, "running"):
            return
        sections.append(
            await run_in_threadpool(
                section_result, output, checks, section_id, missing_voice
            )
        )
        section = sections[-1]
        section["latency_ms"] = int((time.monotonic() - section_started) * 1000)
        bind_claims(section, version.id, offset)
        if section["brief_evidence"]:
            offset += sum(len(p) for p in section["brief_evidence"]["paragraphs"])
        usage.extend(output.get("judge_usage", []))
        # Append only this section to the database snapshot, in the transaction
        # that advances the progress counter. Other readers see both together.
        check.section_results = BriefCitationCheck.section_results.concat([section])
        check.summary_stats = progress_stats(len(sections), total, outline)
        if len(sections) == total:
            check.summary_stats = await run_in_threadpool(
                claim_summary, sections, usage, started, check.judge_model
            )
            check.status = "completed"
            check.finished_at = datetime.now(timezone.utc)
        await session.commit()
    await _record_check_usage(check)


def claim_summary(sections, usage, started, model):
    rows = [row for _, _, row in claim_passages(sections)]
    return {
        **full_summary(rows, sections, usage, started, model),
        "claim_record_version": 1,
    }


def full_summary(rows, sections, usage, started, model):
    from ui.backend.services.citation_check_runner import summarise
    from ui.backend.utils.llm_costs import compute_cost

    stats = summarise(rows, int((time.monotonic() - started) * 1000), model)
    prompt = sum(e.get("prompt_tokens") or 0 for e in usage)
    completion = sum(e.get("completion_tokens") or 0 for e in usage)
    cost = compute_cost(model, prompt, completion)
    stats.update(
        **saved_brief_scores(sections),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cost_usd=float(cost) if cost is not None else None,
        section_counts={
            s: sum(row["status"] == s for row in sections)
            for s in ("pass", "fail", "error")
        },
    )
    return stats
