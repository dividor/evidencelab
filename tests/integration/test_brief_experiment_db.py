"""Brief runs retain their assignment, sibling text and decisions across later edits."""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL
from ui.backend.auth.testing_models import (
    TestCase,
    TestDataset,
    TestExperiment,
    TestResult,
)
from ui.backend.services import test_runner

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_brief_experiment_persists_generation_context_and_repetition_verdict():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            async with AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as session:
                dataset = TestDataset(
                    name="Section comparisons", capability="brief", data_source="uneg"
                )
                session.add(dataset)
                await session.flush()
                case = TestCase(
                    dataset_id=dataset.id,
                    input={
                        "query": "Service quality",
                        "heading": "Duration",
                        "siblings": [
                            {
                                "title": "Earlier finding",
                                "content": "Repairs lasted 48 hours.",
                            }
                        ],
                    },
                )
                session.add(case)
                await session.flush()
                columns = [{"type": "brief_structure"}, {"type": "brief_overlap"}]
                experiment = TestExperiment(
                    name="Repetition",
                    dataset_id=dataset.id,
                    status="draft",
                    config={},
                    case_expectations={
                        "columns": columns,
                        "cases": {str(case.id): {"active": True, "cols": [True, True]}},
                    },
                )
                session.add(experiment)
                await session.flush()

                async def observed(**_kwargs):
                    yield {"type": "token", "token": "Repairs took two days [3]."}
                    yield {
                        "type": "sources",
                        "sources": [{"index": 3, "text": "Repairs took two days."}],
                    }
                    yield {"type": "done", "section_written": True}

                with (
                    patch("ui.backend.utils.app_state.get_db_for_source"),
                    patch("ui.backend.utils.app_state.get_pg_for_source"),
                    patch(
                        "ui.backend.services.brief_experiment.stream_research_response",
                        observed,
                    ),
                    patch.object(
                        test_runner,
                        "_judge_call",
                        return_value=(
                            '{"reason":"Both report the same duration.","score":0}',
                            {},
                        ),
                    ),
                ):
                    await test_runner._execute(session, experiment)
                case.input = {**case.input, "siblings": []}
                await session.commit()
                experiment_id = experiment.id
                session.expire_all()
                saved = (
                    await session.execute(
                        select(TestResult).where(
                            TestResult.experiment_id == experiment_id
                        )
                    )
                ).scalar_one()
                assert saved.status == "fail"
                assert (
                    saved.actual_output["siblings"][0]["content"]
                    == "Repairs lasted 48 hours."
                )
                assert [a["passed"] for a in saved.assertion_results] == [True, False]
                assert saved.actual_output["sources"][0]["index"] == 3
            await outer.rollback()
    finally:
        await engine.dispose()
