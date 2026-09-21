"""Unit tests for the shared rate limiter configuration."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from ui.backend.utils.app_limits import (
    get_rate_limits,
    limiter,
    rate_limit_exceeded_handler,
)

pytestmark = pytest.mark.unit


def _app_with_limit(limit: str) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/ping")
    @limiter.limit(limit)
    async def ping(request: Request):
        return {"ok": True}

    return app


@pytest.fixture
def live_limiter(monkeypatch):
    """The shared limiter, enabled and with a clean window.

    Other test modules switch it off for their API tests and leave it that
    way, so a test that needs real limiting must turn it on itself.
    """
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    yield limiter
    limiter.reset()


class TestLimiterHeaders:
    def test_rate_limited_response_then_carries_retry_after(self, live_limiter):
        # The Heatmapper fans one request out per grid cell and waits for
        # Retry-After on 429 instead of guessing a back-off.
        client = TestClient(_app_with_limit("1/minute"))
        assert client.get("/ping").status_code == 200
        limited = client.get("/ping")
        assert limited.status_code == 429
        assert "retry-after" in limited.headers
        # Seconds until the per-minute window resets: a positive delta, never
        # an epoch timestamp.
        assert 1 <= int(limited.headers["retry-after"]) <= 60
        assert limited.json() == {"error": "Rate limit exceeded: 1 per 1 minute"}


class TestGetRateLimits:
    def test_env_unset_then_defaults(self, monkeypatch):
        for name in ("RATE_LIMIT_SEARCH", "RATE_LIMIT_DEFAULT", "RATE_LIMIT_AI"):
            monkeypatch.delenv(name, raising=False)
        assert get_rate_limits() == ("30/minute", "60/minute", "10/minute")

    def test_env_set_then_used(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_SEARCH", "500/minute")
        assert get_rate_limits()[0] == "500/minute"
