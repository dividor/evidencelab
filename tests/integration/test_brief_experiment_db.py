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
from ui.backend.schemas.testing import TestResultRead
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
                columns = [
                    {"type": "brief_structure"},
                    {"type": "brief_overlap"},
                    {"type": "brief_factual", "rubric": "Check the duration and unit."},
                ]
                experiment = TestExperiment(
                    name="Repetition",
                    dataset_id=dataset.id,
                    status="draft",
                    config={},
                    case_expectations={
                        "columns": columns,
                        "cases": {
                            str(case.id): {"active": True, "cols": [True, True, True]}
                        },
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
                        side_effect=[
                            (
                                '{"reason":"Both report the same duration.",'
                                '"repeats":[{"new_clause":"Repairs took two days",'
                                '"other_heading":"Earlier finding",'
                                '"existing_clause":"Repairs lasted 48 hours"}]}',
                                {},
                            ),
                            (
                                '{"claims":[{"claim":1,"reason":"The source confirms two days.",'
                                '"factual":true,"unmet":[],"score":1}]}',
                                {},
                            ),
                        ],
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
                evidence = TestResultRead.model_validate(saved).brief_evidence
                assert evidence["paragraphs"][0][0]["references"] == [0]
                assert evidence["references"] == [{"label": "3", "source_position": 0}]
                assert (
                    saved.actual_output["sources"][0]["text"]
                    == "Repairs took two days."
                )
                assert (
                    saved.actual_output["siblings"][0]["content"]
                    == "Repairs lasted 48 hours."
                )
                assert [a["passed"] for a in saved.assertion_results] == [
                    True,
                    False,
                    True,
                ]
                factual = TestResultRead.model_validate(saved).assertion_results[2]
                assert factual["factual_support"]
                assert factual["claim_grades"] == [
                    {
                        "claim": 1,
                        "reason": "The source confirms two days.",
                        "score": 1,
                        "passed": True,
                    }
                ]
                assert "Repairs took two days." in factual["judge_prompt"]
                assert saved.actual_output["sources"][0]["index"] == 3
            await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("existing", ["search", "ai_summary", "brief"])
async def test_starter_upgrade_preserves_existing_experiments_and_history(existing):
    """Run the migration against isolated PostgreSQL copies of the real tables."""
    import runpy
    from pathlib import Path

    from sqlalchemy import text

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0044_install_brief_starters.py"
    )
    upgrade = runpy.run_path(str(migration))["upgrade"]
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            for table in (
                TestDataset.__table__,
                TestCase.__table__,
                TestExperiment.__table__,
            ):
                await conn.execute(
                    text(
                        f"CREATE TEMP TABLE {table.name} "
                        f"(LIKE public.{table.name} INCLUDING ALL) ON COMMIT DROP"
                    )
                )
            async with AsyncSession(conn, expire_on_commit=False) as session:
                original = TestDataset(
                    name="Keep this dataset", capability=existing, data_source="other"
                )
                session.add(original)
                await session.flush()
                experiment = TestExperiment(
                    dataset_id=original.id,
                    name="Keep my grading",
                    status="completed",
                    config={"custom": True},
                    summary_stats={"passed": 17},
                )
                session.add(experiment)
                await session.flush()

                def install(connection):
                    with Operations.context(
                        MigrationContext.configure(connection)
                    ), patch(
                        "pipeline.db.config.load_datasources_config",
                        return_value={
                            "datasources": {
                                "Technical library": {"data_subdir": "technical"}
                            }
                        },
                    ):
                        upgrade()

                await conn.run_sync(install)
                await conn.run_sync(install)
                session.expire_all()
                experiments = (await session.scalars(select(TestExperiment))).all()
                assert len(experiments) == (1 if existing == "brief" else 2)
                assert experiment.config == {"custom": True}
                assert experiment.summary_stats == {"passed": 17}
                cases = (await session.scalars(select(TestCase))).all()
                assert len(cases) == (0 if existing == "brief" else 2)
                if cases:
                    assert all(c.input["reference_standard"] == {} for c in cases)
                    assert any(c.input["children"] for c in cases)
    finally:
        await engine.dispose()
