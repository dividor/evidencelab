"""Authentication enforcement middleware for on_active mode.

When ``USER_MODULE_MODE`` is ``on_active``, every request to a data-serving
endpoint must be authenticated.  This middleware checks for a valid session
cookie, Bearer JWT, or API key and returns 401 if none is present.

Routes that handle their own authentication (``/auth/*``, ``/users/*``, etc.)
are exempt.
"""

import hashlib
import logging
import secrets as _secrets

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

AUTH_COOKIE_NAME = "evidencelab_auth"
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = ["fastapi-users:auth"]

# Paths that do not require authentication through this middleware.
# They are either public or enforce their own auth via fastapi-users
# dependencies (current_active_user / current_superuser).
EXEMPT_PATH_PREFIXES = (
    "/health",
    "/auth/",
    "/config/auth-status",
    "/users/",
    "/groups/",
    "/ratings/",
    "/activity/",
    "/api-keys",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class ActiveAuthMiddleware(BaseHTTPMiddleware):
    """Deny unauthenticated requests to data endpoints in on_active mode."""

    def __init__(
        self,
        app: ASGIApp,
        auth_secret: str,
        api_key: str | None = None,
    ) -> None:
        super().__init__(app)
        self._auth_secret = auth_secret
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # CORS preflight must always pass through.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Exempt paths — public or self-authenticated.
        path = request.url.path
        if any(path.startswith(prefix) for prefix in EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        # --- Authentication checks (any one is sufficient) ---

        # 1. Valid API key header
        if await self._has_valid_api_key_async(request):
            return await call_next(request)

        # 2. Valid Authorization: Bearer <jwt>
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            if token and self._has_valid_jwt(token):
                return await call_next(request)

        # 3. Valid session cookie
        cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
        if cookie_token and self._has_valid_jwt(cookie_token):
            return await call_next(request)

        # No valid credentials — deny access.
        logger.info(
            "ActiveAuth denied unauthenticated %s %s from %s",
            request.method,
            path,
            request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    def _has_valid_jwt(self, token: str) -> bool:
        """Return True if *token* is a valid, non-expired JWT."""
        try:
            jwt.decode(
                token,
                self._auth_secret,
                algorithms=[JWT_ALGORITHM],
                audience=JWT_AUDIENCE,
            )
            return True
        except jwt.PyJWTError:
            return False

    async def _has_valid_api_key_async(self, request: Request) -> bool:
        """Return True if the request carries a valid API key header."""
        header_key = request.headers.get("x-api-key", "")
        if not header_key:
            return False
        # Check global env key first (timing-safe)
        if self._api_key and _secrets.compare_digest(header_key, self._api_key):
            return True
        # Check admin-managed keys via cached hashes
        from ui.backend.auth.api_key_cache import get_active_key_hashes

        key_hash = hashlib.sha256(header_key.encode()).hexdigest()
        active_hashes = await get_active_key_hashes()
        return key_hash in active_hashes
