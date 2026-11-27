"""Recover evaluation runs whose background task is gone.

Runs execute as in-process background tasks inside one api copy; every
cloud layout runs two or more copies on one database. A row that says
``running`` may therefore belong to a live runner on another copy, so only
rows without progress for ``job_liveness.STALE_AFTER`` are failed. The
routes call ``fail_stale_runs`` when experiments are listed or opened, and
the api calls ``recover_orphaned_runs`` at start.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.testing_models import (
    EXPERIMENT_FAILED,
    EXPERIMENT_PENDING,
    EXPERIMENT_RUNNING,
    TestExperiment,
    TestRun,
)
from ui.backend.services.job_liveness import is_stale, orphan_message, utcnow

logger = logging.getLogger(__name__)

ACTIVE = (EXPERIMENT_RUNNING, EXPERIMENT_PENDING)


def _stale(row: Any, now: datetime) -> bool:
    return row.status in ACTIVE and is_stale(
        row.summary_stats, row.started_at, row.created_at, now
    )


def _orphan(row: Any, now: datetime) -> None:
    row.status = EXPERIMENT_FAILED
    row.finished_at = now
    row.summary_stats = {
        "error": orphan_message(row.summary_stats, row.started_at, row.created_at, now)
    }


async def fail_stale_runs(session, now: Optional[datetime] = None) -> int:
    """Fail the pending/running runs that have shown no progress for
    ``job_liveness.STALE_AFTER``, and the pending/running experiments that
    have no live run and are as old: their background task is gone (the api
    copy running it stopped). A run with a fresh heartbeat belongs to a live
    runner, possibly on another api copy, and is left alone, as is its
    experiment. Returns how many rows were failed."""
    now = now or utcnow()
    active = list(ACTIVE)
    runs = (
        (await session.execute(select(TestRun).where(TestRun.status.in_(active))))
        .scalars()
        .all()
    )
    stale_runs = [run for run in runs if _stale(run, now)]
    live = {run.experiment_id for run in runs if run not in stale_runs}
    experiments = (
        (
            await session.execute(
                select(TestExperiment).where(TestExperiment.status.in_(active))
            )
        )
        .scalars()
        .all()
    )
    stale_experiments = [
        experiment
        for experiment in experiments
        if experiment.id not in live and _stale(experiment, now)
    ]
    for row in [*stale_runs, *stale_experiments]:
        _orphan(row, now)
    if stale_runs or stale_experiments:
        await session.commit()
    return len(stale_runs) + len(stale_experiments)


async def recover_orphaned_runs(session_factory=None) -> None:
    """At api start, fail the runs and experiments whose task is gone
    (``fail_stale_runs``). Not every running one: another api copy may be
    running it."""
    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            recovered = await fail_stale_runs(session)
            if recovered:
                logger.info(
                    "Recovered %s orphaned test run(s)/experiment(s)", recovered
                )
    except Exception:
        logger.exception("Failed to recover orphaned test runs")
