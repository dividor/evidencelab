"""The saved check grades its pinned version and preserves historical citation checks."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL
from ui.backend.auth.models import Brief, User
from ui.backend.auth.testing_models import BriefCitationCheck
from ui.backend.services import brief_fact_check, citation_check_runner, test_runner
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.services.brief_version_store import ensure_version
from ui.backend.services.saved_brief_check_runner import run_full_check

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            async with AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                yield db
            await outer.rollback()
    finally:
        await engine.dispose()


def content(text):
    return convert_legacy(
        dict(
            title="Meter test",
            query="Meter test",
            sections=[
                dict(
                    id="s",
                    title="Readings",
                    level=1,
                    status="done",
                    content=text,
                    sources=[
                        dict(
                            index=1,
                            text="Output rose.",
                            title="Log",
                            docId="d",
                            chunkId="c",
                        )
                    ],
                )
            ],
        )
    )[0]


async def test_saved_and_historical_check_remain_distinct_after_an_edit(
    session, monkeypatch
):
    owner = User(id=uuid4(), email=f"{uuid4()}@example.org", hashed_password="unused")
    session.add(owner)
    await session.flush()
    brief = Brief(
        user_id=owner.id,
        title="Meter test",
        content=content("Output rose [1]. Losses tripled."),
    )
    session.add(brief)
    await session.flush()
    v = await ensure_version(session, brief)
    await session.flush()
    values = dict(
        brief_id=brief.id,
        brief_title=brief.title,
        brief_version_id=v.id,
        brief_version_number=v.number,
    )
    historical = BriefCitationCheck(
        **values, status="completed", summary_stats={"total": 1}
    )
    check = BriefCitationCheck(**values, check_kind="full", status="pending")
    session.add_all([historical, check])
    await session.commit()
    brief.content = content("Edited after starting the check [1].")
    await session.commit()

    async def judge(prompt, model, system, **kwargs):
        if "Claims to grade" in prompt:
            return json.dumps(
                {
                    "claims": [
                        {
                            "claim": 1,
                            "factual": True,
                            "reason": "Recorded.",
                            "score": 1,
                            "unmet": [],
                            "supporting_quotes": [
                                {"citation": 1, "quote": "Output rose."}
                            ],
                        },
                        {
                            "claim": 2,
                            "factual": True,
                            "reason": "No citation.",
                            "score": 0,
                            "unmet": ["Losses tripled"],
                        },
                    ]
                }
            ), {"prompt_tokens": 12}
        return '{"reason":"Clear.","unmet":[],"score":1}', {"prompt_tokens": 3}

    monkeypatch.setattr(test_runner, "_judge_call", judge)
    monkeypatch.setattr(citation_check_runner, "_record_check_usage", AsyncMock())
    await run_full_check(session, check)
    await session.refresh(
        check, ["section_results", "passages", "summary_stats", "status"]
    )
    assert check.status == "completed" and check.summary_stats["prompt_tokens"] == 18
    assert check.summary_stats["section_counts"] == {"pass": 0, "fail": 1, "error": 0}
    [result] = check.section_results
    assert result["actual_output"]["summary"] == "Output rose [1]. Losses tripled."
    assert len(result["assertion_results"]) == 9
    assert [p.verdict for p in check.passages] == ["supported", "unsupported"]
    assert check.passages[0].quotes_verified == "1/1"
    assert not (await brief_fact_check.fact_check(session, brief))["marks"]
    await session.refresh(
        historical, ["section_results", "summary_stats", "check_kind"]
    )
    assert historical.check_kind == "citation" and historical.section_results is None
    assert historical.summary_stats == {"total": 1}
