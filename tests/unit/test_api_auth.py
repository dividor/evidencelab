"""Unit tests for API authentication across all USER_MODULE_MODE values.

Covers:
1. API access requires a key for external users (mode=off with API_KEY set)
2. API key generation and admin-managed key validation
3. Passive mode: anonymous UI browsing allowed, API key still accepted
4. Active mode: requires API key, session cookie, or Bearer JWT
"""

import hashlib
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from ui.backend.auth import api_key_verify

# Dummy values for tests — not real secrets.
_TEST_KEY = "test-dummy-key-not-a-real-secret"  # pragma: allowlist secret
_ALT_KEY = "alt-dummy-key-not-a-real-secret"  # pragma: allowlist secret
_GLOBAL_KEY = "global-dummy-key-not-real"  # pragma: allowlist secret
_JWT_SECRET = "jwt-dummy-secret-32-chars-long!!!"  # pragma: allowlist secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    path: str = "/search",
    method: str = "GET",
    cookies: dict | None = None,
    headers: dict | None = None,
    client_host: str = "127.0.0.1",
):
    """Create a mock Starlette Request."""
    req = MagicMock()
    req.url.path = path
    req.method = method
    req.cookies = cookies or {}
    _headers = headers or {}
    req.headers.get = lambda k, default="": _headers.get(k, default)
    req.client = MagicMock()
    req.client.host = client_host
    return req


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Save and restore api_key_verify module state around each test."""
    saved = (
        api_key_verify.API_KEY,
        api_key_verify.USER_MODULE,
        api_key_verify.USER_MODULE_MODE,
    )
    yield
    (
        api_key_verify.API_KEY,
        api_key_verify.USER_MODULE,
        api_key_verify.USER_MODULE_MODE,
    ) = saved


def _configure(
    api_key: str | None = _TEST_KEY,
    user_module: bool = False,
    mode: str = "off",
):
    """Set api_key_verify module-level config for a test."""
    api_key_verify.API_KEY = api_key
    api_key_verify.USER_MODULE = user_module
    api_key_verify.USER_MODULE_MODE = mode


# ---------------------------------------------------------------------------
# 1. API access requires a key (USER_MODULE_MODE=off, API_KEY set)
# ---------------------------------------------------------------------------


class TestApiKeyRequired:
    """When USER_MODULE is off and API_SECRET_KEY is set, every non-exempt
    request must carry a valid X-API-Key header."""

    @pytest.mark.asyncio
    async def test_no_key_returns_401(self):
        """Request without API key is rejected."""
        _configure(api_key=_TEST_KEY)
        req = _make_request("/search")
        with pytest.raises(HTTPException) as exc_info:
            await api_key_verify.verify_api_key(req, api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_key_returns_401(self):
        """Request with incorrect API key is rejected."""
        _configure(api_key=_TEST_KEY)
        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_key_verify.verify_api_key(req, api_key=_ALT_KEY)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_global_key_allowed(self):
        """Request with the correct global API key passes."""
        _configure(api_key=_TEST_KEY)
        req = _make_request("/search")
        result = await api_key_verify.verify_api_key(req, api_key=_TEST_KEY)
        assert result == _TEST_KEY

    @pytest.mark.asyncio
    async def test_no_api_key_configured_returns_500(self):
        """When API_SECRET_KEY is not set, requests get a 500 error."""
        _configure(api_key=None)
        req = _make_request("/search")
        with pytest.raises(HTTPException) as exc_info:
            await api_key_verify.verify_api_key(req, api_key=None)
        assert exc_info.value.status_code == 500
        assert "API_SECRET_KEY" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_exempt_paths_skip_auth(self):
        """Exempt paths (/health, /docs, /auth/*, etc.) bypass API key."""
        exempt_paths = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/auth/login",
            "/auth/register",
            "/users/me",
            "/groups/list",
            "/ratings/submit",
            "/activity/log",
            "/api-keys",
            "/file/test.pdf",
            "/pdf/test.pdf",
        ]
        _configure(api_key=_TEST_KEY)
        for path in exempt_paths:
            req = _make_request(path)
            result = await api_key_verify.verify_api_key(req, api_key=None)
            assert result is None, f"Path {path} should be exempt"


# ---------------------------------------------------------------------------
# 2. Admin-managed API key generation and validation
# ---------------------------------------------------------------------------


class TestAdminManagedKeys:
    """Admin-generated keys (el_ prefix, SHA-256 hashed) work in verify_api_key."""

    def test_generated_key_format(self):
        """Admin key has el_ prefix and sufficient length."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        assert raw_key.startswith("el_")
        assert len(raw_key) >= 45  # el_ (3) + 43 base64 chars

    def test_key_hash_is_sha256(self):
        """Key hash is a 64-char hex SHA-256 digest."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        assert len(key_hash) == 64
        assert all(c in "0123456789abcdef" for c in key_hash)

    @pytest.mark.asyncio
    async def test_admin_key_accepted(self):
        """Admin-managed key found in cache is accepted."""
        raw_key = "el_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        _configure(api_key=_GLOBAL_KEY)
        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value={key_hash},
        ):
            result = await api_key_verify.verify_api_key(req, api_key=raw_key)
            assert result == raw_key

    @pytest.mark.asyncio
    async def test_admin_key_not_in_cache_rejected(self):
        """Admin key whose hash is not in cache is rejected."""
        raw_key = "el_" + secrets.token_urlsafe(32)

        _configure(api_key=_GLOBAL_KEY)
        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_key_verify.verify_api_key(req, api_key=raw_key)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_global_key_takes_priority(self):
        """Global key matches before checking admin cache (fast path)."""
        _configure(api_key=_GLOBAL_KEY)
        req = _make_request("/search")
        result = await api_key_verify.verify_api_key(req, api_key=_GLOBAL_KEY)
        assert result == _GLOBAL_KEY

    def test_cache_invalidation(self):
        """invalidate_cache resets the in-memory cache."""
        from ui.backend.auth import api_key_cache

        api_key_cache._cache = {"some_hash"}
        api_key_cache.invalidate_cache()
        assert api_key_cache._cache is None


# ---------------------------------------------------------------------------
# 3. Passive mode: anonymous users can browse the app
# ---------------------------------------------------------------------------


class TestPassiveMode:
    """on_passive mode: users can browse the UI without logging in, but
    direct API access still requires a valid API key or session cookie."""

    @pytest.mark.asyncio
    async def test_anonymous_api_request_rejected(self):
        """Anonymous API request (no key, no cookie) is rejected even in
        passive mode — API endpoints always require authentication."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_passive")
        req = _make_request("/search")
        with pytest.raises(HTTPException) as exc_info:
            await api_key_verify.verify_api_key(req, api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_api_key_accepted(self):
        """Providing a valid API key works in passive mode."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_passive")
        req = _make_request("/search")
        result = await api_key_verify.verify_api_key(req, api_key=_TEST_KEY)
        assert result == _TEST_KEY

    @pytest.mark.asyncio
    async def test_session_cookie_accepted(self):
        """Logged-in user with session cookie passes in passive mode."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_passive")
        req = _make_request("/search", cookies={"evidencelab_auth": "jwt-token"})
        result = await api_key_verify.verify_api_key(req, api_key=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_key_rejected_in_passive(self):
        """Wrong API key without session cookie is rejected in passive mode."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_passive")
        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_key_verify.verify_api_key(req, api_key=_ALT_KEY)
            assert exc_info.value.status_code == 401

    def test_no_active_auth_middleware_in_passive(self):
        """ActiveAuthMiddleware is NOT added in on_passive mode — only in
        on_active mode.  Verified by checking the conditional in main.py."""
        import ast
        from pathlib import Path

        main_py = Path(__file__).resolve().parents[2] / "ui" / "backend" / "main.py"
        source = main_py.read_text()
        tree = ast.parse(source)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test = node.test
                if (
                    isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "USER_MODULE_MODE"
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "on_active"
                ):
                    block_src = ast.dump(node)
                    if "ActiveAuthMiddleware" in block_src:
                        found = True
        assert found, (
            "ActiveAuthMiddleware should only be added under "
            '`if USER_MODULE_MODE == "on_active":`'
        )


# ---------------------------------------------------------------------------
# 4. Active mode: locks everything down
# ---------------------------------------------------------------------------


class TestActiveMode:
    """on_active mode requires authentication for all data endpoints.
    Either API key, session cookie (JWT), or Bearer JWT is needed."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_401(self):
        """Request without any credentials is rejected in active mode."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_active")
        req = _make_request("/search")
        with pytest.raises(HTTPException) as exc_info:
            await api_key_verify.verify_api_key(req, api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_api_key_allowed(self):
        """Valid API key passes in active mode."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_active")
        req = _make_request("/search")
        result = await api_key_verify.verify_api_key(req, api_key=_TEST_KEY)
        assert result == _TEST_KEY

    @pytest.mark.asyncio
    async def test_session_cookie_allowed(self):
        """Session cookie passes the verify_api_key check in active mode.
        (ActiveAuthMiddleware does full JWT validation separately.)"""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_active")
        req = _make_request("/search", cookies={"evidencelab_auth": "jwt-tok"})
        result = await api_key_verify.verify_api_key(req, api_key=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_key_no_cookie_returns_401(self):
        """Wrong API key and no session cookie is rejected."""
        _configure(api_key=_TEST_KEY, user_module=True, mode="on_active")
        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_key_verify.verify_api_key(req, api_key=_ALT_KEY)
            assert exc_info.value.status_code == 401


class TestActiveAuthMiddleware:
    """Test the ActiveAuthMiddleware directly for on_active mode."""

    @pytest.mark.asyncio
    async def test_exempt_paths_pass_through(self):
        """Exempt paths (/health, /docs, /auth/*) bypass middleware."""
        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        exempt_paths = [
            "/health",
            "/auth/login",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/users/me",
            "/groups/",
            "/api-keys",
        ]
        for path in exempt_paths:
            req = _make_request(path)
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 200, f"Path {path} should be exempt"

    @pytest.mark.asyncio
    async def test_options_passes_through(self):
        """CORS preflight (OPTIONS) always passes."""
        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search", method="OPTIONS")
        response = await mw.dispatch(req, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_api_key_passes(self):
        """Request with valid API key passes middleware."""
        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search", headers={"x-api-key": _ALT_KEY})
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_key_passes_middleware(self):
        """Request with admin-managed API key passes middleware."""
        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        raw_key = "el_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_GLOBAL_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search", headers={"x-api-key": raw_key})
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value={key_hash},
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_no_credentials_returns_401(self):
        """Request without any credentials returns 401."""
        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_jwt_cookie_passes(self):
        """Request with valid JWT session cookie passes middleware."""
        import jwt as pyjwt

        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        token = pyjwt.encode(
            {"sub": "user-id", "aud": "fastapi-users:auth"},
            _JWT_SECRET,
            algorithm="HS256",
        )

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_JWT_SECRET, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search", cookies={"evidencelab_auth": token})
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_expired_jwt_rejected(self):
        """Expired JWT session cookie is rejected."""
        import time

        import jwt as pyjwt

        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        token = pyjwt.encode(
            {
                "sub": "user-id",
                "aud": "fastapi-users:auth",
                "exp": int(time.time()) - 3600,
            },
            _JWT_SECRET,
            algorithm="HS256",
        )

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_JWT_SECRET, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search", cookies={"evidencelab_auth": token})
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_jwt_passes(self):
        """Request with valid Bearer JWT passes middleware."""
        import jwt as pyjwt

        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        token = pyjwt.encode(
            {"sub": "user-id", "aud": "fastapi-users:auth"},
            _JWT_SECRET,
            algorithm="HS256",
        )

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_JWT_SECRET, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request(
            "/search",
            headers={"authorization": f"Bearer {token}"},
        )
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Cross-cutting edge cases."""

    def test_timing_safe_comparison_used(self):
        """Global key uses secrets.compare_digest (timing-safe)."""
        import inspect

        source = inspect.getsource(api_key_verify.verify_api_key)
        assert (
            "secrets.compare_digest" in source
        ), "verify_api_key must use secrets.compare_digest for global key"

    @pytest.mark.asyncio
    async def test_thumbnail_path_exempt(self):
        """Paths containing /thumbnail are exempt."""
        _configure(api_key=_TEST_KEY)
        req = _make_request("/document/123/thumbnail")
        result = await api_key_verify.verify_api_key(req, api_key=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_401_response_is_json_detail(self):
        """verify_api_key raises HTTPException with a descriptive detail."""
        _configure(api_key=_TEST_KEY)
        req = _make_request("/search")
        with pytest.raises(HTTPException) as exc_info:
            await api_key_verify.verify_api_key(req, api_key=None)
        assert exc_info.value.status_code == 401
        assert isinstance(exc_info.value.detail, str)
        assert len(exc_info.value.detail) > 0

    @pytest.mark.asyncio
    async def test_middleware_401_is_json_response(self):
        """ActiveAuthMiddleware returns JSONResponse for 401."""
        from fastapi.responses import JSONResponse

        from ui.backend.auth.active_auth import ActiveAuthMiddleware

        app_mock = AsyncMock()
        mw = ActiveAuthMiddleware(app_mock, auth_secret=_TEST_KEY, api_key=_ALT_KEY)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req = _make_request("/search")
        with patch(
            "ui.backend.auth.api_key_cache.get_active_key_hashes",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            response = await mw.dispatch(req, call_next)
            assert response.status_code == 401
            assert isinstance(response, JSONResponse)
