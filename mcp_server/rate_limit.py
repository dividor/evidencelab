"""Rate-limiting helpers for MCP tool calls.

Wraps the existing slowapi limiter so that MCP tools can enforce
per-IP rate limits without being wired through FastAPI route decorators.
"""

from __future__ import annotations

import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger(__name__)

RATE_LIMIT_MCP_SEARCH = os.environ.get("RATE_LIMIT_MCP_SEARCH", "30/minute")
RATE_LIMIT_MCP_AI = os.environ.get("RATE_LIMIT_MCP_AI", "10/minute")

# Dedicated limiter for MCP endpoints so limits are tracked independently
# from the main API rate limits.
_mcp_limiter = Limiter(key_func=get_remote_address)


def check_mcp_rate_limit(request: Request, limit_string: str) -> None:
    """Manually check a rate limit for the given request.

    Raises ``slowapi.errors.RateLimitExceeded`` if the limit is breached.
    The caller should convert this into an appropriate MCP error.
    """
    _mcp_limiter.check(limit_string, request)
