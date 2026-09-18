import math
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def get_rate_limits() -> tuple[str, str, str]:
    rate_limit_search = os.environ.get("RATE_LIMIT_SEARCH", "30/minute")
    rate_limit_default = os.environ.get("RATE_LIMIT_DEFAULT", "60/minute")
    rate_limit_ai = os.environ.get("RATE_LIMIT_AI", "10/minute")
    return rate_limit_search, rate_limit_default, rate_limit_ai


def get_rate_limit_translate() -> str:
    return os.environ.get("RATE_LIMIT_TRANSLATE", "60/minute")


limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return the 429 with a ``Retry-After`` header.

    slowapi's default handler only adds headers when the limiter runs with
    ``headers_enabled``, which in turn requires every rate-limited endpoint to
    hand back a ``Response`` object. This handler instead reads the limit slowapi
    records on the request before raising and computes the seconds until that
    window resets, so clients that fan out requests, such as the Heatmapper
    grid, can wait for the reset instead of guessing.
    """
    limit_item, identifiers = request.state.view_rate_limit
    reset_at, _remaining = limiter.limiter.get_window_stats(limit_item, *identifiers)
    retry_after = max(1, math.ceil(reset_at - time.time()))
    response = JSONResponse(
        {"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429
    )
    response.headers["Retry-After"] = str(retry_after)
    return response
