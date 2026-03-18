"""Unit tests for error detail sanitisation (ASVS V7.1.1, V7.4.1)."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ui.backend.auth.security_headers import SecurityHeadersMiddleware


def _make_app(*, debug: bool = False):
    """Create a test app with the same exception handlers as main.py."""
    app = FastAPI()

    _safe_prefixes = ("Invalid data_source:",)

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc):
        msg = str(exc)
        if debug or any(msg.startswith(p) for p in _safe_prefixes):
            return JSONResponse(status_code=400, content={"detail": msg})
        return JSONResponse(
            status_code=400, content={"detail": "Invalid request parameters"}
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        detail = str(exc) if debug else "Internal server error"
        return JSONResponse(status_code=500, content={"detail": detail})

    @app.get("/value-error")
    async def raise_value_error():
        raise ValueError("secret internal table name leaked")

    @app.get("/safe-value-error")
    async def raise_safe_value_error():
        raise ValueError("Invalid data_source: foo. Valid sources: ['bar']")

    @app.get("/server-error")
    async def raise_server_error():
        raise RuntimeError("database connection failed at /var/lib/pg")

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _client(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestValueErrorHandler:
    """Verify ValueError responses are sanitised."""

    @pytest.mark.asyncio
    async def test_generic_value_error_returns_safe_message(self):
        """Non-safe ValueErrors should return a generic message."""
        app = _make_app(debug=False)
        async with _client(app) as client:
            response = await client.get("/value-error")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid request parameters"
        assert "secret" not in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_safe_prefix_returns_actual_message(self):
        """ValueErrors with safe prefixes should return the real message."""
        app = _make_app(debug=False)
        async with _client(app) as client:
            response = await client.get("/safe-value-error")
        assert response.status_code == 400
        assert "Invalid data_source" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_debug_mode_returns_full_detail(self):
        """In debug mode, full error detail should be returned."""
        app = _make_app(debug=True)
        async with _client(app) as client:
            response = await client.get("/value-error")
        assert response.status_code == 400
        assert "secret internal table" in response.json()["detail"]


class TestGenericExceptionHandler:
    """Verify unhandled exceptions return safe 500 responses."""

    @pytest.mark.asyncio
    async def test_returns_generic_500(self):
        """Unhandled exceptions should return 'Internal server error'."""
        app = _make_app(debug=False)
        async with _client(app) as client:
            response = await client.get("/server-error")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"
        assert "database" not in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_debug_mode_returns_full_500_detail(self):
        """In debug mode, the actual exception text should be returned."""
        app = _make_app(debug=True)
        async with _client(app) as client:
            response = await client.get("/server-error")
        assert response.status_code == 500
        assert "database connection failed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_500_response_does_not_leak_details(self):
        """500 responses should not include internal paths or stack traces."""
        app = _make_app(debug=False)
        async with _client(app) as client:
            response = await client.get("/server-error")
        body = response.json()
        assert "/var/lib" not in body["detail"]
        assert "database" not in body["detail"]
