"""Ratings from visitors who are not signed in (``features.anonymous_ratings``).

The ratings router runs in a small FastAPI app with the real limiter; only the
database session and the signed-in user are replaced, so the tests check which
owner each query filters on and which cookie the API sets.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import UserRating
from ui.backend.auth.users import optional_current_user
from ui.backend.routes import ratings
from ui.backend.utils.app_limits import limiter, rate_limit_exceeded_handler

pytestmark = pytest.mark.unit

RATING = {
    "rating_type": "search_result",
    "reference_id": "11111111-1111-1111-1111-111111111111",
    "item_id": "chunk-1",
    "score": 4,
}


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeSession:
    """Records statements and writes; every query returns ``rows``."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.added = []
        self.deleted = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return FakeResult(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        now = datetime.now(timezone.utc)
        obj.id = obj.id or uuid.uuid4()
        obj.created_at = obj.created_at or now
        obj.updated_at = obj.updated_at or now

    async def delete(self, obj):
        self.deleted.append(obj)


def _stored_rating(**overrides):
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rating = UserRating(
        id=uuid.uuid4(),
        user_id=None,
        anonymous_id=uuid.uuid4(),
        rating_type=RATING["rating_type"],
        reference_id=RATING["reference_id"],
        item_id=RATING["item_id"],
        score=2,
        created_at=now,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(rating, key, value)
    return rating


def _filters_on(stmt, column, value):
    """Whether a compiled statement filters ``column`` by ``value``."""
    compiled = stmt.compile()
    return f"user_ratings.{column} =" in str(compiled) and value in (
        compiled.params.values()
    )


@pytest.fixture
def make_client(monkeypatch):
    """Build a client for the ratings router with the given setup."""

    def _make(session, enabled=True, user=None):
        monkeypatch.setattr(
            ratings,
            "get_application_config",
            lambda: {"features": {"anonymous_ratings": enabled}},
        )
        limiter.reset()
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
        app.include_router(ratings.router, prefix="/ratings")

        async def _session():
            yield session

        app.dependency_overrides[get_async_session] = _session
        app.dependency_overrides[optional_current_user] = lambda: user
        return TestClient(app)

    return _make


class TestAnonymousRatingsEnabled:
    def test_on_when_config_sets_true(self, monkeypatch):
        monkeypatch.setattr(
            ratings,
            "get_application_config",
            lambda: {"features": {"anonymous_ratings": True}},
        )
        assert ratings.anonymous_ratings_enabled() is True

    def test_off_when_key_absent(self, monkeypatch):
        monkeypatch.setattr(ratings, "get_application_config", lambda: {"features": {}})
        assert ratings.anonymous_ratings_enabled() is False

    def test_off_when_features_absent(self, monkeypatch):
        monkeypatch.setattr(ratings, "get_application_config", lambda: {})
        assert ratings.anonymous_ratings_enabled() is False


class TestAnonymousSubmit:
    def test_submit_when_off_returns_401_and_stores_nothing(self, make_client):
        session = FakeSession()
        resp = make_client(session, enabled=False).post("/ratings/", json=RATING)
        assert resp.status_code == 401
        assert session.added == []

    def test_first_rating_stores_browser_id_and_sets_cookie(self, make_client):
        session = FakeSession()
        resp = make_client(session).post("/ratings/", json=RATING)

        assert resp.status_code == 200
        stored = session.added[0]
        assert stored.user_id is None
        assert isinstance(stored.anonymous_id, uuid.UUID)
        cookie = resp.headers["set-cookie"]
        assert f"{ratings.RATER_COOKIE_NAME}={stored.anonymous_id}" in cookie
        assert "HttpOnly" in cookie
        assert "anonymous_id" not in resp.json()

    def test_second_rating_from_same_browser_updates_it(self, make_client):
        browser_id = uuid.uuid4()
        existing = _stored_rating(anonymous_id=browser_id)
        session = FakeSession(rows=[existing])
        client = make_client(session)
        client.cookies.set(ratings.RATER_COOKIE_NAME, str(browser_id))

        resp = client.post("/ratings/", json={**RATING, "score": 5})

        assert resp.status_code == 200
        assert session.added == []
        assert existing.score == 5
        assert _filters_on(session.statements[0], "anonymous_id", browser_id)
        assert "set-cookie" not in resp.headers

    def test_malformed_cookie_gets_a_new_browser_id(self, make_client):
        session = FakeSession()
        client = make_client(session)
        client.cookies.set(ratings.RATER_COOKIE_NAME, "not-a-uuid")

        resp = client.post("/ratings/", json=RATING)

        assert resp.status_code == 200
        new_id = session.added[0].anonymous_id
        assert f"{ratings.RATER_COOKIE_NAME}={new_id}" in resp.headers["set-cookie"]

    def test_page_feedback_when_off_is_still_stored_without_owner(self, make_client):
        session = FakeSession()
        feedback = {
            "rating_type": "page_feedback",
            "reference_id": "https://example.org/search?q=x",
            "score": 3,
            "comment": "Button hidden on mobile",
        }
        resp = make_client(session, enabled=False).post("/ratings/", json=feedback)

        assert resp.status_code == 200
        stored = session.added[0]
        assert stored.user_id is None
        assert stored.anonymous_id is None
        assert session.statements == []
        assert "set-cookie" not in resp.headers


class TestSignedInSubmit:
    def test_signed_in_rating_is_owned_by_the_user_not_a_browser(self, make_client):
        user = SimpleNamespace(
            id=uuid.uuid4(), email="rater@example.org", full_name="Rater"
        )
        session = FakeSession()
        resp = make_client(session, enabled=False, user=user).post(
            "/ratings/", json=RATING
        )

        assert resp.status_code == 200
        stored = session.added[0]
        assert stored.user_id == user.id
        assert stored.anonymous_id is None
        assert _filters_on(session.statements[0], "user_id", user.id)
        assert "set-cookie" not in resp.headers


class TestAnonymousReadAndDelete:
    def test_mine_returns_the_browsers_ratings(self, make_client):
        browser_id = uuid.uuid4()
        session = FakeSession(rows=[_stored_rating(anonymous_id=browser_id)])
        client = make_client(session)
        client.cookies.set(ratings.RATER_COOKIE_NAME, str(browser_id))

        resp = client.get("/ratings/mine", params={"rating_type": "search_result"})

        assert resp.status_code == 200
        assert [r["score"] for r in resp.json()] == [2]
        assert _filters_on(session.statements[0], "anonymous_id", browser_id)

    def test_mine_without_cookie_is_empty_and_skips_the_database(self, make_client):
        session = FakeSession(rows=[_stored_rating()])
        resp = make_client(session).get("/ratings/mine")
        assert resp.json() == []
        assert session.statements == []

    def test_mine_when_off_is_empty(self, make_client):
        session = FakeSession(rows=[_stored_rating()])
        client = make_client(session, enabled=False)
        client.cookies.set(ratings.RATER_COOKIE_NAME, str(uuid.uuid4()))
        assert client.get("/ratings/mine").json() == []
        assert session.statements == []

    def test_delete_removes_the_browsers_own_rating(self, make_client):
        browser_id = uuid.uuid4()
        existing = _stored_rating(anonymous_id=browser_id)
        session = FakeSession(rows=[existing])
        client = make_client(session)
        client.cookies.set(ratings.RATER_COOKIE_NAME, str(browser_id))

        resp = client.delete(f"/ratings/{existing.id}")

        assert resp.status_code == 204
        assert session.deleted == [existing]
        assert _filters_on(session.statements[0], "anonymous_id", browser_id)

    def test_delete_when_off_returns_401(self, make_client):
        session = FakeSession(rows=[_stored_rating()])
        client = make_client(session, enabled=False)
        client.cookies.set(ratings.RATER_COOKIE_NAME, str(uuid.uuid4()))
        assert client.delete(f"/ratings/{uuid.uuid4()}").status_code == 401
        assert session.deleted == []


class TestSubmitRateLimit:
    def test_submissions_beyond_the_limit_get_429(self, make_client, monkeypatch):
        # Other route tests switch the shared limiter off when imported.
        monkeypatch.setattr(limiter, "enabled", True)
        session = FakeSession()
        client = make_client(session)
        limit = int(ratings.RATE_LIMIT_RATINGS.split("/")[0])
        codes = [
            client.post("/ratings/", json=RATING).status_code for _ in range(limit + 1)
        ]
        assert codes[:limit] == [200] * limit
        assert codes[limit] == 429
