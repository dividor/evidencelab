"""Start, follow and stop the same versioned check from Brief and Admin."""

from fastapi import HTTPException
from sqlalchemy import func, select

from ui.backend.auth.models import Brief
from ui.backend.auth.testing_models import BriefCitationCheck
from ui.backend.services import brief_version_store as versions
from ui.backend.services.brief_citation_model import is_visible
from ui.backend.services.citation_check_runner import resolve_judge_model, run_check
from ui.backend.services.llm_choice import JUDGE, user_group_choice


def model_combo_names():
    from pipeline.db.config import UI_MODEL_COMBOS

    return list(UI_MODEL_COMBOS)


async def active_run(session, brief_id):
    result = await session.execute(
        select(BriefCitationCheck)
        .where(
            BriefCitationCheck.brief_id == brief_id,
            BriefCitationCheck.status.in_(["pending", "running"]),
        )
        .order_by(BriefCitationCheck.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


def start_disabled_reason(brief, can_edit, checked):
    if not can_edit:
        return "You have read-only access to this brief."
    if not any(
        is_visible(section) for section in (brief.content or {}).get("sections", [])
    ):
        return "Write a section before checking facts."
    if (
        checked["marks"]
        and checked["brief_version"] == checked["current_version"]
        and checked["brief_version"] is not None
    ):
        return "This version has already been checked."
    return None


async def start(session, brief, user, combo, tasks, *, from_document=False):
    # Both entry points take the same lock before looking for an existing run.
    await session.execute(
        select(Brief.id).where(Brief.id == brief.id).with_for_update()
    )
    existing = await active_run(session, brief.id)
    if existing is not None:
        return existing
    await session.refresh(brief, attribute_names=["content", "title"])
    if from_document:
        from ui.backend.services.brief_fact_check import fact_check

        reason = start_disabled_reason(brief, True, await fact_check(session, brief))
        if reason:
            raise HTTPException(409, reason)
    combo = (combo or "").strip() or None
    if combo and combo not in model_combo_names():
        raise HTTPException(400, "Invalid model_combo")
    model = await user_group_choice(session, user, JUDGE) or resolve_judge_model(combo)
    if not model:
        raise HTTPException(503, "No judge model is configured")
    version = await versions.ensure_version(session, brief)
    check = BriefCitationCheck(
        brief_id=brief.id,
        brief_title=brief.title,
        data_source=brief.data_source,
        created_by_user_id=user.id,
        check_kind="full",
        judge_model=model,
        model_combo=combo,
        brief_version_id=version.id,
        brief_version_number=version.number,
        status="pending",
    )
    session.add(check)
    await session.commit()
    await session.refresh(check)
    tasks.add_task(run_check, check.id)
    return check


async def stop(session, check):
    await session.refresh(check, with_for_update=True)
    if check.status in ("pending", "running"):
        check.status = "failed"
        check.finished_at = func.now()
        check.summary_stats = {"error": "Cancelled by user"}
        await session.commit()
        await session.refresh(check)
    return check


def progress(check):
    stats = check.summary_stats or {}
    return dict(
        id=check.id,
        status=check.status,
        stopped=stats.get("error") == "Cancelled by user",
        progress=stats.get("progress"),
    )
