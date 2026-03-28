"""Unit tests for MCP authentication helpers."""

from __future__ import annotations

import hashlib

import pytest
from starlette.requests import Request

from mcp_server.auth import verify_mcp_auth


def _make_request(headers: dict | None = None, cookies: dict | None = None) -> Request:
    """Build a minimal Starlette Request with custom headers/cookies."""
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "query_string": b"",
        "headers": raw_headers,
    }
    req = Request(scope)
    # Inject cookies by overriding the internal state
    if cookies:
        req._cookies = cookies
    return req


# ── API key tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_env_api_key(monkeypatch):
    """A request with the correct API_SECRET_KEY header passes auth."""
    monkeypatch.setenv("API_SECRET_KEY", "test-secret-key-123")

    request = _make_request(headers={"x-api-key": "test-secret-key-123"})
    info = await verify_mcp_auth(request)

    assert info["type"] == "api_key"
    assert info["user_id"] == "env_key"
    expected_hash = hashlib.sha256(b"test-secret-key-123").hexdigest()[:16]
    assert info["key_hash"] == expected_hash


@pytest.mark.asyncio
async def test_valid_admin_api_key(monkeypatch):
    """A request with an admin-managed key that matches the hash cache passes."""
    monkeypatch.setenv("API_SECRET_KEY", "")  # env key does not match
    test_key = "admin-managed-key-456"
    key_hash = hashlib.sha256(test_key.encode()).hexdigest()

    # Mock the admin key cache to return a set containing our hash
    async def fake_get_active_key_hashes():
        return {key_hash}

    monkeypatch.setattr(
        "mcp_server.auth.get_active_key_hashes",
        fake_get_active_key_hashes,
        raising=False,
    )
    # The lazy import inside _check_api_key uses
    # ``from ui.backend.auth.api_key_cache import get_active_key_hashes``,
    # so we also patch the module-level import target.
    import ui.backend.auth.api_key_cache as _cache_mod

    monkeypatch.setattr(_cache_mod, "get_active_key_hashes", fake_get_active_key_hashes)

    request = _make_request(headers={"x-api-key": test_key})
    info = await verify_mcp_auth(request)

    assert info["type"] == "api_key"
    assert info["user_id"] == f"managed:{key_hash[:16]}"


@pytest.mark.asyncio
async def test_invalid_api_key(monkeypatch):
    """A wrong API key with no valid JWT raises PermissionError."""
    monkeypatch.setenv("API_SECRET_KEY", "correct-key")
    monkeypatch.setenv("AUTH_SECRET_KEY", "")  # no JWT fallback

    request = _make_request(headers={"x-api-key": "wrong-key"})
    with pytest.raises(PermissionError, match="Valid API key or JWT required"):
        await verify_mcp_auth(request)


# ── JWT tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_bearer_jwt(monkeypatch):
    """A valid JWT in the Authorization header passes auth."""
    monkeypatch.setenv("API_SECRET_KEY", "")
    monkeypatch.setenv("AUTH_SECRET_KEY", "jwt-secret")

    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": "user-42", "aud": "fastapi-users:auth"},
        "jwt-secret",
        algorithm="HS256",
    )

    request = _make_request(headers={"authorization": f"Bearer {token}"})
    info = await verify_mcp_auth(request)

    assert info["type"] == "jwt"
    assert info["user_id"] == "user-42"
    assert info["key_hash"] is None


@pytest.mark.asyncio
async def test_expired_bearer_jwt(monkeypatch):
    """An expired JWT returns 401 (PermissionError)."""
    monkeypatch.setenv("API_SECRET_KEY", "")
    monkeypatch.setenv("AUTH_SECRET_KEY", "jwt-secret")

    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": "user-42", "aud": "fastapi-users:auth", "exp": 0},
        "jwt-secret",
        algorithm="HS256",
    )

    request = _make_request(headers={"authorization": f"Bearer {token}"})
    with pytest.raises(PermissionError, match="Valid API key or JWT required"):
        await verify_mcp_auth(request)


@pytest.mark.asyncio
async def test_no_credentials(monkeypatch):
    """A request with no auth header/cookie raises PermissionError."""
    monkeypatch.setenv("API_SECRET_KEY", "")
    monkeypatch.setenv("AUTH_SECRET_KEY", "")

    request = _make_request()
    with pytest.raises(PermissionError, match="Valid API key or JWT required"):
        await verify_mcp_auth(request)
