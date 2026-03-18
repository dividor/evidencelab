"""CSRF protection using the double-submit cookie pattern.

How it works:
1. On every response a non-httpOnly ``evidencelab_csrf`` cookie is set with
   a random token (readable by frontend JS).
2. The frontend reads this cookie and sends it back as the ``X-CSRF-Token``
   header on every state-changing request (POST / PUT / PATCH / DELETE).
3. This middleware validates that the header matches the cookie.

Because a cross-origin attacker cannot read another site's cookies (same-
origin policy), they cannot forge the header — defeating CSRF attacks.

Configuration:
    CSRF_ENABLED  Set to "false" to disable (default: "true" when USER_MODULE
                  is active).
"""

import logging
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "evidencelab_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection middleware."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Safe (read-only) methods — no CSRF check needed
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            _ensure_csrf_cookie(request, response)
            return response

        # State-changing request: validate CSRF if cookie is present.
        # If the cookie is absent the user hasn't visited the site via a
        # browser yet, so there's nothing to protect (likely an API-key call).
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        if cookie_token:
            header_token = request.headers.get(CSRF_HEADER_NAME)
            if not header_token or not secrets.compare_digest(
                cookie_token, header_token
            ):
                logger.warning(
                    "CSRF validation failed for %s %s from %s",
                    request.method,
                    request.url.path,
                    request.client.host if request.client else "unknown",
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed"},
                )

        response = await call_next(request)
        _ensure_csrf_cookie(request, response)
        return response


def _ensure_csrf_cookie(request: Request, response) -> None:  # type: ignore[type-arg]
    """Set the CSRF cookie if it isn't already present."""
    if CSRF_COOKIE_NAME not in request.cookies:
        token = secrets.token_hex(32)
        response.set_cookie(
            CSRF_COOKIE_NAME,
            token,
            httponly=False,  # Must be readable by frontend JS
            secure=_COOKIE_SECURE,
            samesite="lax",
            path="/",
        )
