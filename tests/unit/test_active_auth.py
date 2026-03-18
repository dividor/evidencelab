"""Tests for ActiveAuthMiddleware (on_active mode enforcement)."""

import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend.auth.active_auth import ActiveAuthMiddleware

TEST_SECRET = "test-secret-key-for-active-auth-testing"  # pragma: allowlist secret
TEST_API_KEY = "test-key-abc"  # pragma: allowlist secret  # noqa: S105
COOKIE_NAME = "evidencelab_auth"


def _make_jwt(
    secret: str = TEST_SECRET,
    audience: list[str] | None = None,
    expired: bool = False,
) -> str:
    """Create a JWT for testing."""
    payload = {
        "sub": "test-user-id",
        "aud": audience or ["fastapi-users:auth"],
        "exp": int(time.time()) + (-3600 if expired else 3600),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _create_app(api_key: str | None = TEST_API_KEY) -> FastAPI:
    """Build a minimal FastAPI app with ActiveAuthMiddleware."""
    app = FastAPI()
    app.add_middleware(
        ActiveAuthMiddleware,
        auth_secret=TEST_SECRET,
        api_key=api_key,
    )

    @app.get("/search")
    async def search():
        return {"results": []}

    @app.get("/documents")
    async def documents():
        return {"docs": []}

    @app.get("/stats")
    async def stats():
        return {"total": 0}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/config/auth-status")
    async def auth_status():
        return {"mode": "on_active"}

    @app.get("/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/users/me")
    async def me():
        return {"id": "test"}

    @app.get("/groups/")
    async def groups():
        return {"groups": []}

    @app.get("/ratings/")
    async def ratings():
        return {"ratings": []}

    @app.get("/activity/")
    async def activity():
        return {"activity": []}

    @app.get("/pdf/doc-123")
    async def pdf():
        return {"pdf": True}

    @app.get("/highlight/doc-123")
    async def highlight():
        return {"boxes": []}

    return app


# --- Exempt paths ---


class TestExemptPaths:
    """Requests to exempt paths should pass through without auth."""

    def test_health(self):
        client = TestClient(_create_app())
        assert client.get("/health").status_code == 200

    def test_auth_status(self):
        client = TestClient(_create_app())
        assert client.get("/config/auth-status").status_code == 200

    def test_auth_routes(self):
        client = TestClient(_create_app())
        assert client.get("/auth/login").status_code == 200

    def test_users_routes(self):
        client = TestClient(_create_app())
        assert client.get("/users/me").status_code == 200

    def test_groups_routes(self):
        client = TestClient(_create_app())
        assert client.get("/groups/").status_code == 200

    def test_ratings_routes(self):
        client = TestClient(_create_app())
        assert client.get("/ratings/").status_code == 200

    def test_activity_routes(self):
        client = TestClient(_create_app())
        assert client.get("/activity/").status_code == 200

    def test_options_request(self):
        client = TestClient(_create_app())
        resp = client.options("/search")
        assert resp.status_code != 401


# --- Unauthenticated requests denied ---


class TestUnauthenticatedDenied:
    """Data endpoints should return 401 without valid credentials."""

    @pytest.mark.parametrize(
        "path",
        ["/search", "/documents", "/stats", "/pdf/doc-123", "/highlight/doc-123"],
    )
    def test_no_credentials(self, path):
        client = TestClient(_create_app())
        resp = client.get(path)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"


# --- Cookie auth ---


class TestCookieAuth:
    """Valid session cookie should grant access."""

    def test_valid_cookie(self):
        client = TestClient(_create_app())
        token = _make_jwt()
        resp = client.get("/search", cookies={COOKIE_NAME: token})
        assert resp.status_code == 200

    def test_expired_cookie(self):
        client = TestClient(_create_app())
        token = _make_jwt(expired=True)
        resp = client.get("/search", cookies={COOKIE_NAME: token})
        assert resp.status_code == 401

    def test_wrong_secret_cookie(self):
        client = TestClient(_create_app())
        token = _make_jwt(secret="wrong-secret-key-xxxxxxxxxxxxxxxxx")
        resp = client.get("/search", cookies={COOKIE_NAME: token})
        assert resp.status_code == 401

    def test_wrong_audience_cookie(self):
        client = TestClient(_create_app())
        token = _make_jwt(audience=["wrong-audience"])
        resp = client.get("/search", cookies={COOKIE_NAME: token})
        assert resp.status_code == 401


# --- Bearer token auth ---


class TestBearerAuth:
    """Valid Authorization: Bearer header should grant access."""

    def test_valid_bearer(self):
        client = TestClient(_create_app())
        token = _make_jwt()
        resp = client.get("/search", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_expired_bearer(self):
        client = TestClient(_create_app())
        token = _make_jwt(expired=True)
        resp = client.get("/search", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_invalid_bearer(self):
        client = TestClient(_create_app())
        resp = client.get("/search", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401


# --- API key auth ---


class TestApiKeyAuth:
    """Valid X-API-Key header should grant access."""

    def test_valid_api_key(self):
        client = TestClient(_create_app())
        resp = client.get("/search", headers={"X-API-Key": TEST_API_KEY})
        assert resp.status_code == 200

    def test_invalid_api_key(self):
        client = TestClient(_create_app())
        resp = client.get("/search", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_no_api_key_configured(self):
        """When no API key is configured, API key auth is unavailable."""
        client = TestClient(_create_app(api_key=None))
        resp = client.get("/search", headers={"X-API-Key": "anything"})
        assert resp.status_code == 401
