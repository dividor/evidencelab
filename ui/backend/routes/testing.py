"""Admin Search & AI-Summary evaluation harness — superuser-only routes.

Datasets of reusable test cases, experiments that exercise the live search /
AI-summary capabilities, and per-test pass/fail results. Every endpoint is
gated with ``Depends(current_superuser)`` and rate-limited; experiments run as
FastAPI background tasks (the UI polls status). Errors are returned generically
per SECURITY.md; full detail is logged server-side only.
"""

import logging
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User
from ui.backend.auth.testing_models import (
    EXPERIMENT_DRAFT,
    EXPERIMENT_PENDING,
    EXPERIMENT_RUNNING,
    VALID_CAPABILITIES,
    TestCase,
    TestDataset,
    TestExperiment,
    TestResult,
)
from ui.backend.auth.users import current_superuser
from ui.backend.schemas.testing import (
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
    TestResultRead,
)
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
    background_tasks.add_task(run_experiment, experiment.id)
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
    experiment = await _get_experiment(session, experiment_id)
    stmt = (
        select(TestResult)
        .where(TestResult.experiment_id == experiment_id)
        .order_by(TestResult.created_at.asc())
    )
    results = (await session.execute(stmt)).scalars().all()
    detail = TestExperimentDetail.model_validate(experiment)
    detail.results = [TestResultRead.model_validate(r) for r in results]
    return detail
