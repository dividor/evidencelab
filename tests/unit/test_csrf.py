"""Unit tests for CSRF double-submit cookie middleware."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from ui.backend.auth.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    _ensure_csrf_cookie,
)


def _make_app():
    """Create a minimal FastAPI app with CSRF middleware for testing."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/get-endpoint")
    async def get_endpoint():
        return {"status": "ok"}

    @app.post("/post-endpoint")
    async def post_endpoint():
        return {"status": "created"}

    @app.put("/put-endpoint")
    async def put_endpoint():
        return {"status": "updated"}

    @app.delete("/delete-endpoint")
    async def delete_endpoint():
        return {"status": "deleted"}

    app.add_middleware(CSRFMiddleware)
    return app


def _client(app):
    """Create an httpx.AsyncClient for testing the ASGI app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestCSRFMiddlewareSafeMethods:
    """GET, HEAD, OPTIONS should pass without CSRF validation."""

    @pytest.mark.asyncio
    async def test_get_request_passes_without_csrf(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/get-endpoint")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_request_sets_csrf_cookie(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/get-endpoint")
        cookie_names = [c.name for c in response.cookies.jar]
        assert CSRF_COOKIE_NAME in cookie_names

    @pytest.mark.asyncio
    async def test_head_request_not_blocked_by_csrf(self):
        """HEAD is a safe method — CSRF middleware should never block it."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.head("/get-endpoint")
        # FastAPI may return 200 or 405 for HEAD, but CSRF must not block it
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_options_request_passes(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.options("/get-endpoint")
        # FastAPI may return 405 for OPTIONS if not explicitly defined,
        # but CSRF middleware should not block it
        assert response.status_code != 403


class TestCSRFMiddlewareStateMethods:
    """POST, PUT, DELETE should validate CSRF when cookie present."""

    @pytest.mark.asyncio
    async def test_post_without_csrf_cookie_passes(self):
        """If no CSRF cookie is present (first visit / API call), allow through."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.post("/post-endpoint")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_with_cookie_but_no_header_fails(self):
        """CSRF cookie present but header missing -> 403."""
        app = _make_app()
        csrf_token = "test-csrf-token-value"  # pragma: allowlist secret
        async with _client(app) as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            response = await client.post("/post-endpoint")
        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_with_cookie_and_matching_header_passes(self):
        """Cookie + matching header -> allowed."""
        app = _make_app()
        csrf_token = "valid-token-1234abcd"  # pragma: allowlist secret
        async with _client(app) as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            response = await client.post(
                "/post-endpoint",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_with_cookie_and_wrong_header_fails(self):
        """Cookie + non-matching header -> 403."""
        app = _make_app()
        async with _client(app) as client:
            client.cookies.set(CSRF_COOKIE_NAME, "cookie-token-abc")
            response = await client.post(
                "/post-endpoint",
                headers={CSRF_HEADER_NAME: "wrong-header-token"},
            )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_put_with_cookie_requires_header(self):
        """PUT requests also require CSRF validation."""
        app = _make_app()
        csrf_token = "put-csrf-token"  # pragma: allowlist secret
        async with _client(app) as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            # Without header
            response = await client.put("/put-endpoint")
            assert response.status_code == 403
            # With header
            response = await client.put(
                "/put-endpoint",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_with_cookie_requires_header(self):
        """DELETE requests also require CSRF validation."""
        app = _make_app()
        csrf_token = "delete-csrf-token"  # pragma: allowlist secret
        async with _client(app) as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            # Without header
            response = await client.delete("/delete-endpoint")
            assert response.status_code == 403
            # With header
            response = await client.delete(
                "/delete-endpoint",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert response.status_code == 200


class TestCSRFCookieGeneration:
    """Tests for the _ensure_csrf_cookie helper."""

    def test_cookie_not_set_when_already_present(self):
        """If the CSRF cookie already exists, don't overwrite it."""
        request = MagicMock()
        request.cookies = {CSRF_COOKIE_NAME: "existing-token"}
        response = MagicMock()
        _ensure_csrf_cookie(request, response)
        response.set_cookie.assert_not_called()

    def test_cookie_set_when_absent(self):
        """If no CSRF cookie, set one on the response."""
        request = MagicMock()
        request.cookies = {}
        response = MagicMock()
        with patch("ui.backend.auth.csrf.secrets.token_hex", return_value="abc123"):
            _ensure_csrf_cookie(request, response)
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args
        assert call_kwargs[0][0] == CSRF_COOKIE_NAME  # cookie name
        assert call_kwargs[0][1] == "abc123"  # token value
        assert call_kwargs[1]["httponly"] is False  # must be JS-readable

    def test_csrf_token_is_random(self):
        """Each new CSRF token should be unique."""
        tokens = []
        for _ in range(5):
            request = MagicMock()
            request.cookies = {}
            response = MagicMock()
            _ensure_csrf_cookie(request, response)
            token = response.set_cookie.call_args[0][1]
            tokens.append(token)
        # All tokens should be unique
        assert len(set(tokens)) == 5
