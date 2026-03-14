"""Security response headers middleware.

Adds standard headers that mitigate common web vulnerabilities such as
clickjacking, MIME-sniffing, and referrer leakage.  These are defence-in-
depth measures — they do not replace proper input validation or auth.

In production, the reverse proxy (Caddy) may add its own headers; setting
them here ensures protection even when the API is accessed directly.
"""

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"

# Only send HSTS when we know the deployment is behind HTTPS
_HSTS_VALUE = "max-age=31536000; includeSubDomains; preload" if _COOKIE_SECURE else ""

# Content-Security-Policy — configurable via CSP_POLICY env var.
# SHA-256 hash of the inline GA consent-check script in index.html.
# If the inline script changes, regenerate with:
#   python3 -c "import hashlib,base64; ..." (see index.html comment)
_GA_SCRIPT_HASH = (
    "'sha256-+j8RgTT7AgjLIJM+Zq61Yo+VpZeip3D+e9hNGrkqHvw='"  # pragma: allowlist secret
)

_CSP_DEFAULT = (
    "default-src 'self'; "
    f"script-src 'self' {_GA_SCRIPT_HASH} "
    "https://www.googletagmanager.com https://www.google-analytics.com; "
    "style-src 'self' 'unsafe-inline'; "  # React style injection requires this
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://www.google-analytics.com "
    "https://www.googletagmanager.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_CSP_POLICY = os.environ.get("CSP_POLICY", _CSP_DEFAULT)

if not _COOKIE_SECURE:
    logger.warning(
        "AUTH_COOKIE_SECURE is disabled — cookies sent over HTTP. "
        "Only use in local development."
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security-related HTTP response headers."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    # Paths whose responses must never be cached (auth, user data, etc.)
    _SENSITIVE_PREFIXES = ("/auth/", "/users/", "/groups/", "/ratings/", "/activity/")

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
        response.headers["Content-Security-Policy"] = _CSP_POLICY

        if _HSTS_VALUE:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        # Prevent caching of sensitive endpoints (ASVS V8.1.4)
        path = request.url.path
        if any(path.startswith(p) for p in self._SENSITIVE_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

        return response
