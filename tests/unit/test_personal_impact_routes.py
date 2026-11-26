"""HTTP contract for personal impact without a live database."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend.auth.db import get_async_session
from ui.backend.auth.users import current_active_user
from ui.backend.routes import llm_usage, users
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
_URL = "/llm-usage/me/footprint"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 5, tzinfo=tz)


@pytest.fixture
def client_and_session(monkeypatch):
    monkeypatch.setattr(llm_usage, "datetime", FixedDatetime)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(llm_usage.router, prefix="/llm-usage")
    app.include_router(users.router, prefix="/users")
    session = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: session
    return TestClient(app), session


@pytest.fixture
def signed_in(client_and_session):
    client, session = client_and_session
    user = SimpleNamespace(id=uuid4(), is_superuser=False)
    client.app.dependency_overrides[current_active_user] = lambda: user
    return client, session, user.id


def _group_rows(*settings):
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [
        SimpleNamespace(search_settings=group_settings) for group_settings in settings
    ]
    return rows


def _impact_row(**overrides):
    row = MagicMock()
    row.mappings.return_value.one.return_value = {
        **dict.fromkeys(llm_usage._FOOTPRINT_COLUMNS),
        "completion_tokens": 0,
        "footprint_unestimated_tokens": 0,
        **overrides,
    }
    return row


def test_summary_when_signed_out_returns_unauthorized(client_and_session):
    client, session = client_and_session
    assert client.get(_URL).status_code == 401
    session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "params,expected_from",
    [
        ({}, date(2026, 2, 4)),
        ({"period": "30-days"}, date(2026, 2, 4)),
        ({"period": "year-to-date"}, date(2026, 1, 1)),
    ],
)
def test_summary_uses_period_and_signed_in_id(signed_in, params, expected_from):
    client, session, user_id = signed_in
    session.execute.side_effect = [
        _group_rows(),
        _impact_row(
            energy_kwh_min=0, completion_tokens=90, footprint_unestimated_tokens=10
        ),
    ]
    response = client.get(_URL, params={**params, "user_id": str(uuid4())})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {
        **dict.fromkeys(llm_usage._FOOTPRINT_COLUMNS),
        "energy_kwh_min": 0,
        "completion_tokens": 90,
        "footprint_unestimated_tokens": 10,
        "estimated_output_tokens": 80,
        "coverage_label": "about 89%",
        "from_date": expected_from.isoformat(),
        "to_date": "2026-03-05",
    }
    sql, bindings = session.execute.await_args.args
    assert "WHERE ua.user_id = :user_id" in str(sql)
    assert bindings == {
        "user_id": user_id,
        "from_dt": datetime.combine(
            expected_from, datetime.min.time(), tzinfo=timezone.utc
        ),
        "to_dt": datetime(2026, 3, 6, tzinfo=timezone.utc),
    }


def test_summary_when_empty_preserves_null_estimates(signed_in):
    client, session, _ = signed_in
    session.execute.side_effect = [_group_rows(), _impact_row()]
    payload = client.get(_URL).json()
    assert payload["completion_tokens"] == 0
    assert payload["footprint_unestimated_tokens"] == 0
    assert payload["estimated_output_tokens"] == 0
    assert payload["coverage_label"] is None
    assert all(payload[column] is None for column in llm_usage._FOOTPRINT_COLUMNS)


@pytest.mark.parametrize(
    "total,unestimated,estimated,label",
    [
        (473_180, 417_977, 55_203, "about 12%"),
        (100, 100, 0, None),
        (100, 0, 100, "all"),
        (1_000, 999, 1, "less than 1%"),
        (1_000, 1, 999, "more than 99%"),
    ],
)
def test_summary_reports_output_coverage(
    signed_in, total, unestimated, estimated, label
):
    client, session, _ = signed_in
    session.execute.side_effect = [
        _group_rows(),
        _impact_row(completion_tokens=total, footprint_unestimated_tokens=unestimated),
    ]
    response = client.get(_URL)
    assert response.status_code == 200
    assert response.json()["estimated_output_tokens"] == estimated
    assert response.json()["coverage_label"] == label


def test_summary_when_period_is_invalid_rejects_the_request(signed_in):
    client, session, _ = signed_in
    assert client.get(_URL, params={"period": "all-time"}).status_code == 422
    session.execute.assert_not_awaited()


def test_summary_and_menu_when_first_group_disables_are_both_off(signed_in):
    client, session, _ = signed_in
    session.execute.return_value = _group_rows(
        {"personalEnvironmentalImpact": False}, {"personalEnvironmentalImpact": True}
    )
    assert client.get("/users/me/effective-settings").json() == {
        "personalEnvironmentalImpact": False
    }
    assert client.get(_URL).status_code == 403
    assert session.execute.await_count == 2  # Only group lookups, no usage query.


def test_menu_setting_when_no_group_sets_it_is_on(signed_in):
    client, session, _ = signed_in
    session.execute.return_value = _group_rows({"rerank": False})
    assert client.get("/users/me/effective-settings").json() == {
        "personalEnvironmentalImpact": True,
        "rerank": False,
    }
