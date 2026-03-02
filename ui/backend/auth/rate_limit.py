"""Rate limiting for authentication endpoints.

Uses a simple in-memory sliding window to throttle login/register attempts
per IP address.  This protects against brute-force and credential-stuffing
attacks without requiring an external store like Redis.

Configuration (environment variables):
    AUTH_RATE_LIMIT_MAX     Max requests per window (default: 10)
    AUTH_RATE_LIMIT_WINDOW  Window size in seconds  (default: 60)
"""

import contextvars
import logging
import os
import time
from collections import defaultdict

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Context variable to share the client IP with downstream code (e.g. audit
# logging inside UserManager.authenticate which has no access to Request).
current_request_ip: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_request_ip", default="unknown"
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUTH_RATE_LIMIT_MAX = int(os.environ.get("AUTH_RATE_LIMIT_MAX", "10"))
AUTH_RATE_LIMIT_WINDOW = int(os.environ.get("AUTH_RATE_LIMIT_WINDOW", "60"))

# ---------------------------------------------------------------------------
# In-memory store: IP → list of request timestamps (monotonic clock)
# ---------------------------------------------------------------------------

_request_log: dict[str, list[float]] = defaultdict(list)

# Periodic garbage-collection counter (avoid unbounded memory growth)
_GC_INTERVAL = 500  # run GC every N calls
_call_count = 0


def _gc_expired_entries() -> None:
    """Remove IPs whose timestamps have all expired."""
    cutoff = time.monotonic() - AUTH_RATE_LIMIT_WINDOW
    expired_ips = [ip for ip, ts in _request_log.items() if not ts or ts[-1] <= cutoff]
    for ip in expired_ips:
        del _request_log[ip]


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def check_auth_rate_limit(request: Request) -> None:
    """Enforce per-IP rate limiting on authentication routes.

    Intended to be used as a FastAPI dependency on the auth router::

        app.include_router(
            auth_routes.router,
            prefix="/auth",
            dependencies=[Depends(check_auth_rate_limit)],
        )

    Raises:
        HTTPException: 429 when the rate limit is exceeded.
    """
    global _call_count  # noqa: PLW0603

    client = request.client
    ip = client.host if client else "unknown"
    current_request_ip.set(ip)
    now = time.monotonic()
    window_start = now - AUTH_RATE_LIMIT_WINDOW

    # Prune expired entries for this IP
    _request_log[ip] = [t for t in _request_log[ip] if t > window_start]

    if len(_request_log[ip]) >= AUTH_RATE_LIMIT_MAX:
        logger.warning("Auth rate limit exceeded for IP %s", ip)
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Please try again later.",
        )

    _request_log[ip].append(now)

    # Periodic garbage collection of stale IPs
    _call_count += 1
    if _call_count >= _GC_INTERVAL:
        _call_count = 0
        _gc_expired_entries()
