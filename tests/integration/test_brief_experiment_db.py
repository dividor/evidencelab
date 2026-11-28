"""Brief runs retain their assignment, sibling text and decisions across later edits."""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL
from ui.backend.auth.models import BriefTemplate, User
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
                from uuid import uuid4

                owner = User(
                    id=uuid4(), email=f"{uuid4()}@example.org", hashed_password="unused"
                )
                session.add(owner)
                await session.flush()
                case = BriefTemplate(
                    user_id=owner.id,
                    name="Service quality",
                    with_text=True,
                    headings=[
                        {"title": "Duration"},
                        {
                            "title": "Earlier finding",
                            "text": "Repairs lasted 48 hours.",
                        },
                    ],
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

                async def observed(**args):
                    if args["query"] == "Earlier finding":
                        yield {"type": "done", "section_written": False}
                        return
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
                                '"assessment":"Both give the same repair time.",'
                                '"existing_clause":"Repairs lasted 48 hours"}]}',
                                {},
                            ),
                            (
                                '{"claims":[{"claim":1,"reason":"The source confirms two days.",'
                                '"factual":true,"unmet":[],"score":1,'
                                '"supporting_quotes":[{"citation":3,"quote":"two days"}]}]}',
                                {},
                            ),
                        ],
                    ),
                ):
                    await test_runner._execute(session, experiment)
                case.headings = [{"title": "Changed heading"}]
                await session.commit()
                experiment_id = experiment.id
                session.expire_all()
                saved = (
                    (
                        await session.execute(
                            select(TestResult).where(
                                TestResult.experiment_id == experiment_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(saved) == 2
                saved = next(
                    r
                    for r in saved
                    if r.actual_output["assignment"]["heading"] == "Duration"
                )
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
                overlap = saved.assertion_results[1]
                assert overlap["repetitions"] == [
                    {
                        "source_index": 0,
                        "source_quote": "Repairs lasted 48 hours",
                        "target_quote": "Repairs took two days",
                        "assessment": "Both give the same repair time.",
                    }
                ]
                factual = TestResultRead.model_validate(saved).assertion_results[2]
                assert factual["factual_support"]
                assert factual["claim_grades"] == [
                    {
                        "claim": 1,
                        "reason": "The source confirms two days.",
                        "factual": True,
                        "unmet": [],
                        "supporting_quotes": [{"citation": 3, "quote": "two days"}],
                        "score": 1,
                        "passed": True,
                        "outcome": "assessed",
                        "verdict": "supported",
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
                assert len(experiments) == 1
                assert experiment.config == {"custom": True}
                assert experiment.summary_stats == {"passed": 17}
                cases = (await session.scalars(select(TestCase))).all()
                assert cases == []
    finally:
        await engine.dispose()


async def test_missing_draft_migration_updates_only_unwritten_brief_results_and_totals():
    from uuid import uuid4

    from sqlalchemy import text

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    migrate = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("0046_unwritten_brief_errors")
        .module.upgrade
    )
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            for query in (
                "CREATE TEMP TABLE test_experiments (id uuid, status text, summary_stats jsonb)",
                "CREATE TEMP TABLE test_runs (id uuid, experiment_id uuid, run_number int, "
                "status text, summary_stats jsonb)",
                "CREATE TEMP TABLE test_results (run_id uuid, status text, score numeric, "
                "actual_output jsonb, assertion_results jsonb, error_message text)",
            ):
                await conn.execute(text(query))
            experiment, run = uuid4(), uuid4()
            ids = {"exp": experiment, "run": run}
            await conn.execute(
                text("INSERT INTO test_experiments VALUES (:exp, 'completed', '{}')"),
                ids,
            )
            await conn.execute(
                text(
                    "INSERT INTO test_runs VALUES (:run, :exp, 1, 'completed', "
                    "jsonb_build_object('cost_usd', 0.2))"
                ),
                ids,
            )
            await conn.execute(
                text(
                    """
                INSERT INTO test_results VALUES
                (:run,'fail',0,jsonb_build_object('capability','brief','written',false),
                    '[{"type":"brief_length"}]',NULL),
                (:run,'fail',0.5,jsonb_build_object('capability','brief','written',true,
                    'summary','A draft'),'[]',NULL),
                (:run,'pass',1,jsonb_build_object('capability','search'),'[]',NULL)
            """
                ),
                ids,
            )

            def apply(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migrate()

            await conn.run_sync(apply)
            await conn.run_sync(apply)
            row = (
                await conn.execute(
                    text(
                        "SELECT status,score,assertion_results FROM test_results "
                        "WHERE actual_output->>'written'='false'"
                    )
                )
            ).one()
            assert (
                row.status == "error"
                and row.score is None
                and row.assertion_results[0]["not_run"]
            )
            stats = (
                await conn.execute(text("SELECT summary_stats FROM test_runs"))
            ).scalar_one()
            assert stats == {
                "passed": 1,
                "failed": 1,
                "errored": 1,
                "pass_rate": 0.3333,
                "mean_score": 0.75,
                "cost_usd": 0.2,
            }
            assert (
                await conn.execute(text("SELECT summary_stats FROM test_experiments"))
            ).scalar_one() == stats
            await conn.rollback()
    finally:
        await engine.dispose()


async def test_score_migration_preserves_recorded_grades_and_nonbrief_runs():
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(
        "0048_brief_score_summaries"
    )

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.module.upgrade()

    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            for statement in (
                "CREATE TEMP TABLE test_datasets (id int, capability text)",
                "CREATE TEMP TABLE test_experiments (id int, dataset_id int, "
                "status text, summary_stats jsonb)",
                "CREATE TEMP TABLE test_runs (id int, experiment_id int, run_number int, "
                "status text, summary_stats jsonb)",
                "CREATE TEMP TABLE test_results (run_id int, assertion_results jsonb)",
                "CREATE TEMP TABLE brief_citation_checks (id int, status text, check_kind text, "
                "section_results jsonb, summary_stats jsonb)",
                "INSERT INTO test_datasets VALUES (1,'brief'),(2,'search')",
                "INSERT INTO test_experiments VALUES "
                "(1,1,'completed','{}'),(2,2,'completed','{}')",
                """INSERT INTO test_runs VALUES (1,1,1,'completed','{"total": 1}'),
                (2,2,1,'completed','{"total": 1}')""",
            ):
                await conn.execute(text(statement))
            assertions = [
                dict(
                    type="brief_factual",
                    score=0,
                    claim_grades=[dict(score=0.8, passed=False)],
                )
            ]
            section = dict(status="fail", assertion_results=assertions)
            await conn.execute(
                text("INSERT INTO test_results VALUES (1,:grades)").bindparams(
                    bindparam("grades", type_=JSONB)
                ),
                {"grades": assertions},
            )
            await conn.execute(
                text(
                    "INSERT INTO brief_citation_checks VALUES "
                    "(1,'completed','full',:sections,'{}'), "
                    "(2,'running','full',:sections,'{}')"
                ).bindparams(bindparam("sections", type_=JSONB)),
                {"sections": [section]},
            )
            await conn.run_sync(upgrade)
            await conn.run_sync(upgrade)
            metrics = dict(factual_claim_mean_score=0.8, factual_claim_pass_rate=0)
            checks = await conn.execute(
                text(
                    "SELECT section_results, summary_stats FROM brief_citation_checks ORDER BY id"
                )
            )
            assert checks.all() == [
                ([section], dict(pass_rate=0, mean_score=0, **metrics)),
                ([section], {}),
            ]
            assert (
                await conn.scalars(text("SELECT assertion_results FROM test_results"))
            ).all() == [assertions]
            runs = await conn.scalars(
                text("SELECT summary_stats FROM test_runs ORDER BY id")
            )
            assert runs.all() == [dict(total=1, **metrics), {"total": 1}]
            parents = await conn.scalars(
                text("SELECT summary_stats FROM test_experiments ORDER BY id")
            )
            assert parents.all() == [metrics, {}]
    finally:
        await engine.dispose()
