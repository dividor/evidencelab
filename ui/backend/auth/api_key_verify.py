"""API key verification logic.

Extracted from ``main.py`` so that it can be unit-tested without pulling
in the heavy pipeline / embedding imports that ``main.py`` transitively
requires.  ``main.py`` re-exports the function via::

    from ui.backend.auth.api_key_verify import verify_api_key
"""

import hashlib
import logging
import secrets

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Module-level state set by main.py at startup.
API_KEY: str | None = None
USER_MODULE: bool = False
USER_MODULE_MODE: str = "off"  # "off" | "on_passive" | "on_active"

# Paths exempt from API-key authentication.
_EXEMPT_PREFIXES = (
    "/auth/",
    "/users/",
    "/groups/",
    "/ratings/",
    "/activity/",
    "/api-keys",
    "/file/",
    "/pdf/",
)
_EXEMPT_EXACT = frozenset(("/health", "/docs", "/redoc", "/openapi.json"))


async def verify_api_key(request: Request, api_key: str | None) -> str | None:
    """Verify the API key from request header, or valid session cookie.

    Returns the validated key string, or ``None`` if the request is
    allowed through without a key.  Raises ``HTTPException(401)`` if
    the request is denied.
    """
    path = request.url.path

    # --- Exempt paths ---
    if path in _EXEMPT_EXACT:
        return None
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return None
    if "/thumbnail" in path:
        return None

    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: API_SECRET_KEY is not set.",
        )

    # Check API key first (external / Swagger users)
    if api_key:
        # Check global env key (fast path, timing-safe)
        if secrets.compare_digest(api_key, API_KEY):
            return api_key
        # Check admin-managed keys via cached SHA-256 hashes
        from ui.backend.auth.api_key_cache import get_active_key_hashes

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        active_hashes = await get_active_key_hashes()
        if key_hash in active_hashes:
            return api_key

    # Allow authenticated UI users through (session cookie / Bearer JWT).
    # ActiveAuthMiddleware performs full validation; here we just check for
    # the presence of a cookie so the dependency doesn't reject logged-in
    # browser requests that don't carry an API key header.
    if USER_MODULE and request.cookies.get("evidencelab_auth"):
        return None

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
