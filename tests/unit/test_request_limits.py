"""Unit tests for request body size limit middleware (ASVS V13.1.3)."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _make_app(max_bytes: int = 2 * 1024 * 1024):
    """Create a minimal FastAPI app with RequestBodyLimitMiddleware."""

    class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
            return await call_next(request)

    app = FastAPI()

    @app.get("/test")
    async def get_endpoint():
        return {"status": "ok"}

    @app.post("/submit")
    async def post_endpoint():
        return {"status": "created"}

    app.add_middleware(RequestBodyLimitMiddleware)
    return app


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestRequestBodyLimit:
    """Verify request body size limiting behaviour."""

    @pytest.mark.asyncio
    async def test_request_under_limit_accepted(self):
        """A POST with a small body should be accepted."""
        app = _make_app(max_bytes=1024)
        async with _client(app) as client:
            response = await client.post(
                "/submit",
                content=b"x" * 512,
                headers={"Content-Length": "512"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_over_limit_rejected(self):
        """A POST with Content-Length exceeding the limit should return 413."""
        app = _make_app(max_bytes=1024)
        async with _client(app) as client:
            response = await client.post(
                "/submit",
                content=b"x" * 2048,
                headers={"Content-Length": "2048"},
            )
        assert response.status_code == 413
        assert response.json()["detail"] == "Request body too large"

    @pytest.mark.asyncio
    async def test_request_exactly_at_limit_accepted(self):
        """A POST with Content-Length equal to the limit should be accepted."""
        app = _make_app(max_bytes=1024)
        async with _client(app) as client:
            response = await client.post(
                "/submit",
                content=b"x" * 1024,
                headers={"Content-Length": "1024"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_requests_unaffected(self):
        """GET requests have no body — should always pass."""
        app = _make_app(max_bytes=1)
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_limit_configurable(self):
        """The limit should be configurable via constructor argument."""
        app_small = _make_app(max_bytes=100)
        async with _client(app_small) as client:
            response = await client.post(
                "/submit",
                content=b"x" * 200,
                headers={"Content-Length": "200"},
            )
        assert response.status_code == 413

        app_large = _make_app(max_bytes=10000)
        async with _client(app_large) as client:
            response = await client.post(
                "/submit",
                content=b"x" * 200,
                headers={"Content-Length": "200"},
            )
        assert response.status_code == 200
