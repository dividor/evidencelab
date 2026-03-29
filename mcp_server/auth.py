"""MCP authentication helpers.

Validates API keys and Bearer JWTs for MCP tool calls.  Reuses the
same credential stores and algorithms as the main FastAPI application.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets

import jwt
from starlette.requests import Request

logger = logging.getLogger(__name__)

# These constants mirror ui.backend.auth.active_auth so JWT validation
# is consistent across the application.
AUTH_COOKIE_NAME = "evidencelab_auth"
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = ["fastapi-users:auth"]


async def verify_mcp_auth(request: Request) -> dict:
    """Validate an API key or Bearer JWT on an incoming MCP request.

    Returns a dict describing the authenticated principal::

        {"type": "api_key" | "jwt", "user_id": ..., "key_hash": ...}

    Raises ``PermissionError`` when no valid credential is found.
    """
    # 1. Check X-API-Key header
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header:
        info = await _check_api_key(api_key_header)
        if info is not None:
            return info

    # 2. Check Authorization: Bearer <jwt>
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            info = _check_jwt(token)
            if info is not None:
                return info

    # 3. Check session cookie
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
    if cookie_token:
        info = _check_jwt(cookie_token)
        if info is not None:
            return info

    raise PermissionError("Valid API key or JWT required for MCP access")


async def _check_api_key(key: str) -> dict | None:
    """Return auth info if *key* matches the global env key or an admin-managed key."""
    env_key = os.environ.get("API_SECRET_KEY", "")
    if env_key and secrets.compare_digest(key, env_key):
        return {
            "type": "api_key",
            "user_id": "env_key",
            "key_hash": hashlib.sha256(key.encode()).hexdigest()[:16],
        }

    # Check admin-managed keys (lazy import to avoid circular deps)
    try:
        from ui.backend.auth.api_key_cache import get_active_key_hashes

        key_hash = hashlib.sha256(key.encode()).hexdigest()
        active_hashes = await get_active_key_hashes()
        if key_hash in active_hashes:
            return {
                "type": "api_key",
                "user_id": f"managed:{key_hash[:16]}",
                "key_hash": key_hash[:16],
            }
    except ImportError:
        # User module not installed — admin-managed keys unavailable
        logger.debug("Admin key cache not available (user module not installed)")
    except Exception:
        # DB or cache error — log at WARNING so it surfaces in monitoring
        logger.warning("Admin key cache lookup failed", exc_info=True)

    return None


def _check_jwt(token: str) -> dict | None:
    """Return auth info if *token* is a valid, non-expired JWT."""
    auth_secret = os.environ.get("AUTH_SECRET_KEY", "")
    if not auth_secret:
        return None
    try:
        payload = jwt.decode(
            token,
            auth_secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
        )
        user_id = payload.get("sub", "unknown")
        return {
            "type": "jwt",
            "user_id": str(user_id),
            "key_hash": None,
        }
    except jwt.PyJWTError:
        return None
