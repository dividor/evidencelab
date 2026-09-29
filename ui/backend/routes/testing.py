"""Admin Search & AI-Summary evaluation harness — superuser-only routes.

Datasets of reusable test cases, experiments that exercise the live search /
AI-summary capabilities, and per-test pass/fail results. Every endpoint is
gated with ``Depends(current_superuser)`` and rate-limited; experiments run as
FastAPI background tasks (the UI polls status). Errors are returned generically
per SECURITY.md; full detail is logged server-side only.
"""

import logging
import uuid
from typing import Dict, List, Optional, Tuple

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import Brief, BriefShare, User
from ui.backend.auth.testing_models import (
    EXPERIMENT_DRAFT,
    EXPERIMENT_FAILED,
    EXPERIMENT_PENDING,
    EXPERIMENT_RUNNING,
    VALID_CAPABILITIES,
    BriefCitationCheck,
    TestCase,
    TestDataset,
    TestExperiment,
    TestRun,
)
from ui.backend.auth.users import current_superuser
from ui.backend.schemas.testing import (
    BriefCheckCandidate,
    BriefCitationCheckCreate,
    BriefCitationCheckDetail,
    BriefCitationCheckPassageRead,
    BriefCitationCheckRead,
    TestCaseCreate,
    TestCaseRead,
    TestCaseUpdate,
    TestDatasetCreate,
    TestDatasetRead,
    TestDatasetUpdate,
    TestExperimentCreate,
    TestExperimentDetail,
    TestExperimentRead,
    TestExperimentUpdate,
)
from ui.backend.services.brief_sharing import user_group_ids
from ui.backend.services.citation_check_runner import (
    build_review_workbook,
    count_cited_passages,
    resolve_judge_model,
    run_check,
)
from ui.backend.services.citation_fidelity import researched_sections
from ui.backend.services.test_runner import run_experiment
from ui.backend.utils.app_limits import get_rate_limits, limiter

logger = logging.getLogger(__name__)

router = APIRouter()
_RL_SEARCH, _RL_DEFAULT, _RL_AI = get_rate_limits()


# ---------------------------------------------------------------------------
# Validation / lookup helpers
# ---------------------------------------------------------------------------


def _validate_capability(capability: str) -> None:
    if capability not in VALID_CAPABILITIES:
        raise HTTPException(status_code=400, detail="Invalid capability")


def _validate_data_source(source: str) -> None:
    """Validate against the config.json whitelist (canonical app_state path)."""
    from ui.backend.utils.app_state import get_db_for_source

    try:
        get_db_for_source(source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid data_source: {source}")
    except Exception:
        logger.exception("data_source validation failed")
        raise HTTPException(status_code=400, detail="Invalid data_source")


async def _get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> TestDataset:
    dataset = await session.get(TestDataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> TestCase:
    case = await session.get(TestCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    return case


async def _get_experiment(
    session: AsyncSession, experiment_id: uuid.UUID
) -> TestExperiment:
    experiment = await session.get(TestExperiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


async def _dataset_read(session: AsyncSession, dataset: TestDataset) -> TestDatasetRead:
    num_cases = await session.scalar(
        select(func.count(TestCase.id)).where(TestCase.dataset_id == dataset.id)
    )
    last_exp = await session.scalar(
        select(TestExperiment)
        .where(TestExperiment.dataset_id == dataset.id)
        .order_by(TestExperiment.created_at.desc())
        .limit(1)
    )
    read = TestDatasetRead.model_validate(dataset)
    read.num_cases = int(num_cases or 0)
    if last_exp is not None:
        read.last_run_at = last_exp.created_at
        read.last_pass_rate = (last_exp.summary_stats or {}).get("pass_rate")
    return read


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


@router.post(
    "/datasets", response_model=TestDatasetRead, status_code=201, tags=["testing"]
)
@limiter.limit(_RL_DEFAULT)
async def create_dataset(
    request: Request,
    body: TestDatasetCreate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestDatasetRead:
    _validate_capability(body.capability)
    _validate_data_source(body.data_source)
    dataset = TestDataset(
        name=body.name,
        description=body.description,
        capability=body.capability,
        data_source=body.data_source,
        created_by_user_id=admin.id,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return await _dataset_read(session, dataset)


@router.get("/datasets", response_model=List[TestDatasetRead], tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def list_datasets(
    request: Request,
    capability: Optional[str] = Query(None),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[TestDatasetRead]:
    stmt = select(TestDataset).order_by(TestDataset.created_at.desc())
    if capability:
        stmt = stmt.where(TestDataset.capability == capability)
    datasets = (await session.execute(stmt)).scalars().all()
    return [await _dataset_read(session, ds) for ds in datasets]


@router.get("/datasets/{dataset_id}", response_model=TestDatasetRead, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def get_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestDatasetRead:
    dataset = await _get_dataset(session, dataset_id)
    return await _dataset_read(session, dataset)


@router.put("/datasets/{dataset_id}", response_model=TestDatasetRead, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def update_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    body: TestDatasetUpdate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestDatasetRead:
    dataset = await _get_dataset(session, dataset_id)
    if body.data_source is not None:
        _validate_data_source(body.data_source)
        dataset.data_source = body.data_source
    if body.name is not None:
        dataset.name = body.name
    if body.description is not None:
        dataset.description = body.description
    await session.commit()
    await session.refresh(dataset)
    return await _dataset_read(session, dataset)


@router.delete("/datasets/{dataset_id}", status_code=204, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def delete_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    dataset = await _get_dataset(session, dataset_id)
    await session.delete(dataset)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}/cases", response_model=List[TestCaseRead], tags=["testing"]
)
@limiter.limit(_RL_DEFAULT)
async def list_cases(
    request: Request,
    dataset_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[TestCase]:
    await _get_dataset(session, dataset_id)
    stmt = (
        select(TestCase)
        .where(TestCase.dataset_id == dataset_id)
        .order_by(TestCase.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/datasets/{dataset_id}/cases",
    response_model=TestCaseRead,
    status_code=201,
    tags=["testing"],
)
@limiter.limit(_RL_DEFAULT)
async def create_case(
    request: Request,
    dataset_id: uuid.UUID,
    body: TestCaseCreate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestCase:
    await _get_dataset(session, dataset_id)
    case = TestCase(
        dataset_id=dataset_id,
        input=body.input,
        tags=body.tags,
        notes=body.notes,
    )
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return case


@router.put("/cases/{case_id}", response_model=TestCaseRead, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def update_case(
    request: Request,
    case_id: uuid.UUID,
    body: TestCaseUpdate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestCase:
    case = await _get_case(session, case_id)
    if body.input is not None:
        case.input = body.input
    if body.tags is not None:
        case.tags = body.tags
    if body.notes is not None:
        case.notes = body.notes
    await session.commit()
    await session.refresh(case)
    return case


@router.delete("/cases/{case_id}", status_code=204, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def delete_case(
    request: Request,
    case_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    case = await _get_case(session, case_id)
    await session.delete(case)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


@router.post(
    "/experiments", response_model=TestExperimentRead, status_code=201, tags=["testing"]
)
@limiter.limit(_RL_DEFAULT)
async def create_experiment(
    request: Request,
    body: TestExperimentCreate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestExperiment:
    """Create a draft experiment (define dataset + per-row assertions); not run."""
    await _get_dataset(session, body.dataset_id)
    experiment = TestExperiment(
        dataset_id=body.dataset_id,
        name=body.name,
        status=EXPERIMENT_DRAFT,
        config=body.config,
        case_expectations=body.case_expectations,
        created_by_user_id=admin.id,
    )
    session.add(experiment)
    await session.commit()
    await session.refresh(experiment)
    return experiment


@router.put(
    "/experiments/{experiment_id}", response_model=TestExperimentRead, tags=["testing"]
)
@limiter.limit(_RL_DEFAULT)
async def update_experiment(
    request: Request,
    experiment_id: uuid.UUID,
    body: TestExperimentUpdate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestExperiment:
    """Edit an experiment's name / config / per-row assertions (not while running)."""
    experiment = await _get_experiment(session, experiment_id)
    if experiment.status == EXPERIMENT_RUNNING:
        raise HTTPException(status_code=409, detail="Experiment is running")
    if body.name is not None:
        experiment.name = body.name
    if body.config is not None:
        experiment.config = body.config
    if body.case_expectations is not None:
        experiment.case_expectations = body.case_expectations
    await session.commit()
    await session.refresh(experiment)
    return experiment


@router.post(
    "/experiments/{experiment_id}/run",
    response_model=TestExperimentRead,
    tags=["testing"],
)
@limiter.limit(_RL_AI)
async def run_experiment_endpoint(
    request: Request,
    experiment_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestExperiment:
    """Run (or re-run) the experiment in the background; the UI polls status."""
    experiment = await _get_experiment(session, experiment_id)
    if experiment.status == EXPERIMENT_RUNNING:
        raise HTTPException(status_code=409, detail="Experiment is already running")
    experiment.status = EXPERIMENT_PENDING
    await session.commit()
    await session.refresh(experiment)
    # Capture the triggering admin's id here — the request context is gone by
    # the time the background task runs — so the run's token usage is
    # attributed to the user who actually clicked Run.
    background_tasks.add_task(
        run_experiment, experiment.id, triggered_by_user_id=admin.id
    )
    return experiment


@router.post(
    "/experiments/{experiment_id}/cancel",
    response_model=TestExperimentRead,
    tags=["testing"],
)
@limiter.limit(_RL_DEFAULT)
async def cancel_experiment(
    request: Request,
    experiment_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestExperiment:
    """Cancel/clear a running experiment: mark its in-flight run + the
    experiment as failed so it stops showing as running and can be re-run.

    (The background task cannot be force-killed; this clears the stuck state.)
    """
    experiment = await _get_experiment(session, experiment_id)
    active = [EXPERIMENT_RUNNING, EXPERIMENT_PENDING]
    await session.execute(
        update(TestRun)
        .where(TestRun.experiment_id == experiment_id, TestRun.status.in_(active))
        .values(
            status=EXPERIMENT_FAILED,
            finished_at=func.now(),
            summary_stats={"error": "Cancelled by user"},
        )
    )
    experiment.status = EXPERIMENT_FAILED
    experiment.summary_stats = {"error": "Cancelled by user"}
    await session.commit()
    await session.refresh(experiment)
    return experiment


@router.get("/experiments", response_model=List[TestExperimentRead], tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def list_experiments(
    request: Request,
    dataset_id: Optional[uuid.UUID] = Query(None),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[TestExperiment]:
    stmt = select(TestExperiment).order_by(TestExperiment.created_at.desc())
    if dataset_id is not None:
        stmt = stmt.where(TestExperiment.dataset_id == dataset_id)
    return list((await session.execute(stmt)).scalars().all())


@router.get(
    "/experiments/{experiment_id}",
    response_model=TestExperimentDetail,
    tags=["testing"],
)
@limiter.limit(_RL_DEFAULT)
async def get_experiment(
    request: Request,
    experiment_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> TestExperimentDetail:
    # Eager-load runs + their results so Pydantic's from_attributes
    # serialization does not trigger an async lazy-load outside the greenlet
    # (MissingGreenlet).
    stmt = (
        select(TestExperiment)
        .where(TestExperiment.id == experiment_id)
        .options(selectinload(TestExperiment.runs).selectinload(TestRun.results))
    )
    experiment = (await session.execute(stmt)).scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    detail = TestExperimentDetail.model_validate(experiment)
    detail.runs.sort(key=lambda r: r.run_number, reverse=True)
    for run in detail.runs:
        run.results.sort(key=lambda r: r.created_at)
    return detail


@router.delete("/experiments/{experiment_id}", status_code=204, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def delete_experiment(
    request: Request,
    experiment_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    experiment = await _get_experiment(session, experiment_id)
    await session.delete(experiment)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Brief citation checks (Evaluation Harness "Brief" type)
# ---------------------------------------------------------------------------

_BRIEF_NOT_FOUND = "Brief not found"
_CHECK_NOT_FOUND = "Check not found"


async def _accessible_briefs(
    session: AsyncSession, user: User
) -> List[Tuple[Brief, bool]]:
    """The user's own briefs plus those shared with them (directly or via a
    group), newest first, as ``(brief, shared)`` pairs."""
    own = (
        await session.execute(select(Brief).where(Brief.user_id == user.id))
    ).scalars()
    briefs = [(b, False) for b in own]
    group_ids = await user_group_ids(session, user.id)
    condition = BriefShare.shared_user_id == user.id
    if group_ids:
        condition = condition | BriefShare.group_id.in_(group_ids)
    shared = (
        await session.execute(
            select(Brief)
            .join(BriefShare, BriefShare.brief_id == Brief.id)
            .where(condition, Brief.user_id != user.id)
            .distinct()
        )
    ).scalars()
    briefs.extend((b, True) for b in shared)
    briefs.sort(key=lambda pair: pair[0].updated_at or pair[0].created_at, reverse=True)
    return briefs


async def _accessible_brief(
    session: AsyncSession, brief_id: uuid.UUID, user: User
) -> Brief:
    for brief, _shared in await _accessible_briefs(session, user):
        if brief.id == brief_id:
            return brief
    raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)


async def _latest_checks(
    session: AsyncSession, brief_ids: List[uuid.UUID]
) -> Dict[uuid.UUID, BriefCitationCheck]:
    if not brief_ids:
        return {}
    rows = (
        await session.execute(
            select(BriefCitationCheck)
            .where(BriefCitationCheck.brief_id.in_(brief_ids))
            .order_by(BriefCitationCheck.created_at.desc())
        )
    ).scalars()
    latest: Dict[uuid.UUID, BriefCitationCheck] = {}
    for check in rows:
        latest.setdefault(check.brief_id, check)
    return latest


async def _owner_names(
    session: AsyncSession, user_ids: List[uuid.UUID]
) -> Dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    # User eager-loads collections, so the result must be de-duplicated.
    result = await session.execute(
        select(User).where(User.__table__.c.id.in_(user_ids))
    )
    users = result.unique().scalars()
    return {u.id: (u.full_name or u.email) for u in users}


@router.get("/briefs", response_model=List[BriefCheckCandidate], tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def list_checkable_briefs(
    request: Request,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[BriefCheckCandidate]:
    """Briefs the current user can check: their own and those shared with them."""
    pairs = await _accessible_briefs(session, admin)
    latest = await _latest_checks(session, [b.id for b, _ in pairs])
    owners = await _owner_names(session, list({b.user_id for b, _ in pairs}))
    out = []
    for brief, shared in pairs:
        content = brief.content or {}
        out.append(
            BriefCheckCandidate(
                id=brief.id,
                title=brief.title,
                data_source=brief.data_source,
                updated_at=brief.updated_at or brief.created_at,
                owner_name=owners.get(brief.user_id, ""),
                shared=shared,
                researched_sections=len(researched_sections(content)),
                cited_passages=count_cited_passages(content),
                last_check=(
                    BriefCitationCheckRead.model_validate(latest[brief.id])
                    if brief.id in latest
                    else None
                ),
            )
        )
    return out


async def _get_check(
    session: AsyncSession, check_id: uuid.UUID, user: User
) -> BriefCitationCheck:
    check = await session.get(BriefCitationCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail=_CHECK_NOT_FOUND)
    # A check is visible to whoever can see its brief; a brief deleted since
    # cascades the check away, so a surviving check always has one.
    await _accessible_brief(session, check.brief_id, user)
    return check


@router.post(
    "/brief-checks",
    response_model=BriefCitationCheckRead,
    status_code=201,
    tags=["testing"],
)
@limiter.limit(_RL_AI)
async def create_brief_check(
    request: Request,
    body: BriefCitationCheckCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> BriefCitationCheck:
    """Start a citation check of a brief in the background; the UI polls."""
    brief = await _accessible_brief(session, body.brief_id, admin)
    combo = (body.model_combo or "").strip() or None
    if combo is not None and combo not in _model_combo_names():
        raise HTTPException(status_code=400, detail="Invalid model_combo")
    judge_model = resolve_judge_model(combo)
    if not judge_model:
        raise HTTPException(status_code=503, detail="No judge model is configured")
    check = BriefCitationCheck(
        brief_id=brief.id,
        brief_title=brief.title,
        data_source=brief.data_source,
        created_by_user_id=admin.id,
        judge_model=judge_model,
        model_combo=combo,
        status=EXPERIMENT_PENDING,
        summary_stats=None,
    )
    session.add(check)
    await session.commit()
    await session.refresh(check)
    background_tasks.add_task(run_check, check.id)
    return check


def _model_combo_names() -> List[str]:
    from pipeline.db.config import UI_MODEL_COMBOS

    return list(UI_MODEL_COMBOS)


@router.get(
    "/brief-checks", response_model=List[BriefCitationCheckRead], tags=["testing"]
)
@limiter.limit(_RL_DEFAULT)
async def list_brief_checks(
    request: Request,
    brief_id: uuid.UUID = Query(...),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> List[BriefCitationCheck]:
    """All checks of one brief, newest first."""
    await _accessible_brief(session, brief_id, admin)
    result = await session.execute(
        select(BriefCitationCheck)
        .where(BriefCitationCheck.brief_id == brief_id)
        .order_by(BriefCitationCheck.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/brief-checks/{check_id}",
    response_model=BriefCitationCheckDetail,
    tags=["testing"],
)
@limiter.limit(_RL_DEFAULT)
async def get_brief_check(
    request: Request,
    check_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> BriefCitationCheck:
    check = await _get_check(session, check_id, admin)
    await session.refresh(check, attribute_names=["passages"])
    return check


@router.post(
    "/brief-checks/{check_id}/cancel",
    response_model=BriefCitationCheckRead,
    tags=["testing"],
)
@limiter.limit(_RL_DEFAULT)
async def cancel_brief_check(
    request: Request,
    check_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> BriefCitationCheck:
    """Mark an in-flight check failed; the runner stops at its next passage."""
    check = await _get_check(session, check_id, admin)
    if check.status in (EXPERIMENT_RUNNING, EXPERIMENT_PENDING):
        check.status = EXPERIMENT_FAILED
        check.finished_at = func.now()
        check.summary_stats = {"error": "Cancelled by user"}
        await session.commit()
        await session.refresh(check)
    return check


@router.delete("/brief-checks/{check_id}", status_code=204, tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def delete_brief_check(
    request: Request,
    check_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    check = await _get_check(session, check_id, admin)
    await session.delete(check)
    await session.commit()
    return Response(status_code=204)


@router.get("/brief-checks/{check_id}/export.xlsx", tags=["testing"])
@limiter.limit(_RL_DEFAULT)
async def export_brief_check(
    request: Request,
    check_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """The review workbook (Flagged / All judgements / Summary), as the
    notebook writes it."""
    check = await _get_check(session, check_id, admin)
    await session.refresh(check, attribute_names=["passages"])
    passages = [
        BriefCitationCheckPassageRead.model_validate(p).model_dump()
        for p in check.passages
    ]
    stats = check.summary_stats or {}
    payload = await run_in_threadpool(
        build_review_workbook, passages, stats.get("by_section") or []
    )
    filename = f"citation_check_{check.brief_id}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
