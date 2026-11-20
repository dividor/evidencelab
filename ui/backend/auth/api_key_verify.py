"""API key verification logic.

Extracted from ``main.py`` so that it can be unit-tested without pulling
in the heavy pipeline / embedding imports that ``main.py`` transitively
requires.  ``main.py`` re-exports the function via::

    from ui.backend.auth.api_key_verify import verify_api_key
"""

import hashlib
import logging
import re
import secrets

from fastapi import HTTPException, Request

from ui.backend.auth.request_checks import is_exempt_path, is_valid_session_token

logger = logging.getLogger(__name__)

# Module-level state set by main.py at startup.
API_KEY: str | None = None
AUTH_SECRET: str = ""
# The key built into the web interface (REACT_APP_API_KEY). Anyone who loads
# the site can read it. It opens the API for the open demo (sign-in off or
# on_passive) but never counts as authentication when sign-in is required.
BROWSER_KEY: str | None = None
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
# Document thumbnails load as <img> tags, which cannot send the key header.
_THUMBNAIL_PATH = re.compile(r"^/document/[^/]+/thumbnail$")


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
    if is_exempt_path(path, _EXEMPT_PREFIXES):
        return None
    if _THUMBNAIL_PATH.match(path):
        return None

    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: API_SECRET_KEY is not set.",
        )

    # The web interface's public key: accepted for the open demo, ignored when
    # sign-in is required (the request must then carry a valid session).
    if api_key and BROWSER_KEY and secrets.compare_digest(api_key, BROWSER_KEY):
        if USER_MODULE_MODE != "on_active":
            return api_key
        api_key = None

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

    # Allow signed-in UI users through on a valid session cookie. The token is
    # verified here, not just looked for: in on_passive mode no middleware
    # checks it later, so a made-up cookie would otherwise pass.
    if USER_MODULE and is_valid_session_token(
        request.cookies.get("evidencelab_auth", ""), AUTH_SECRET
    ):
        return None

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
