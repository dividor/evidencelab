"""Verify personal footprint totals against Postgres in a rolled-back transaction."""

import secrets
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL, get_async_session
from ui.backend.auth.models import User, UserActivity
from ui.backend.auth.users import current_active_user
from ui.backend.routes import llm_usage
from ui.backend.utils.app_limits import limiter

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 5, tzinfo=tz)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            async with AsyncSession(bind=conn) as db:
                yield db
            await transaction.rollback()
    finally:
        await engine.dispose()


def _user():
    return User(
        email=f"{uuid4()}@example.org",
        hashed_password=secrets.token_urlsafe(32),
    )


def _activity(user_id, at, tokens, energy=None, unestimated=None, kind="search"):
    return UserActivity(
        user_id=user_id,
        search_id=uuid4(),
        query="Personal impact test",
        filters={"type": kind},
        created_at=datetime.fromisoformat(at).replace(tzinfo=timezone.utc),
        completion_tokens=tokens,
        energy_kwh_min=energy,
        energy_kwh_max=energy,
        gwp_kgco2eq_min=energy,
        gwp_kgco2eq_max=energy,
        water_l_min=energy,
        water_l_max=energy,
        footprint_unestimated_tokens=unestimated,
    )


async def test_personal_impact_totals_only_the_signed_in_account_in_each_period(
    session, monkeypatch
):
    monkeypatch.setattr(llm_usage, "datetime", FixedDatetime)
    viewer, other = _user(), _user()
    session.add_all([viewer, other])
    await session.flush()
    session.add_all(
        [
            _activity(viewer.id, "2026-02-04T00:00:00", 100, 1, 20),
            _activity(viewer.id, "2026-03-05T23:59:59", 50),
            _activity(viewer.id, "2026-01-01T00:00:00", 200, 2),
            _activity(viewer.id, "2025-12-31T23:59:59", 1000, 10),
            _activity(viewer.id, "2026-03-06T00:00:00", 1000, 10),
            _activity(other.id, "2026-03-05", 1000, 10),
            _activity(None, "2026-03-05", 1000, 10),
            _activity(None, "2026-03-05", 1000, 10, kind="pipeline"),
        ]
    )
    await session.flush()

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(llm_usage.router, prefix="/llm-usage")
    app.dependency_overrides[current_active_user] = lambda: viewer
    app.dependency_overrides[get_async_session] = lambda: session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        url = "/llm-usage/me/footprint"
        month = await client.get(url, params={"user_id": str(other.id)})
        year = await client.get(url, params={"period": "year-to-date"})

    assert month.status_code == year.status_code == 200
    for measure in llm_usage._FOOTPRINT_COLUMNS:
        assert month.json()[measure] == 1
        assert year.json()[measure] == 3
    assert month.json()["completion_tokens"] == 150
    assert year.json()["completion_tokens"] == 350
    assert month.json()["footprint_unestimated_tokens"] == 70
    assert year.json()["footprint_unestimated_tokens"] == 70
    assert month.json()["estimated_output_tokens"] == 80
    assert year.json()["estimated_output_tokens"] == 280
    assert month.json()["coverage_label"] == "about 53%"
    assert year.json()["coverage_label"] == "about 80%"
