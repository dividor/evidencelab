"""Security response headers middleware.

Adds standard headers that mitigate common web vulnerabilities such as
clickjacking, MIME-sniffing, and referrer leakage.  These are defence-in-
depth measures — they do not replace proper input validation or auth.

In production, the reverse proxy (Caddy) may add its own headers; setting
them here ensures protection even when the API is accessed directly.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"

# Only send HSTS when we know the deployment is behind HTTPS
_HSTS_VALUE = "max-age=31536000; includeSubDomains" if _COOKIE_SECURE else ""


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security-related HTTP response headers."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):  # type: ignore[override]
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # Modern browsers should use CSP; disable legacy XSS filter
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        if _HSTS_VALUE:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        return response
