"""Rate limits for MCP tools and A2A skills, counted per caller.

Each caller (a signed-in user, or an API key) gets its own allowance, taken
from the auth context that MCP and A2A set for every request
(``mcp_server.audit.request_auth``). Counting by caller rather than by client
address matters behind the reverse proxy, where every request arrives from
the proxy's address.

Limits come from ``RATE_LIMIT_MCP_SEARCH`` (search, get_document, and Heatmapper) and
``RATE_LIMIT_MCP_AI`` (the assistant), in the usual ``"10/minute"`` form.
"""

from __future__ import annotations

import logging
import os

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from mcp_server.audit import request_auth

logger = logging.getLogger(__name__)

RATE_LIMIT_MCP_SEARCH = os.environ.get("RATE_LIMIT_MCP_SEARCH", "30/minute")
RATE_LIMIT_MCP_AI = os.environ.get("RATE_LIMIT_MCP_AI", "10/minute")

_LIMITS = {"search": RATE_LIMIT_MCP_SEARCH, "ai": RATE_LIMIT_MCP_AI}
_limiter = MovingWindowRateLimiter(MemoryStorage())


class McpRateLimitExceeded(Exception):
    """Raised when a caller has used up its allowance for a kind of call."""


def _caller() -> str:
    auth = request_auth.get()
    return str(auth.get("key_hash") or auth.get("user_id") or "unknown")


def rate_limit_allowance(kind: str) -> int:
    """Return the maximum units available per window."""
    return parse(_LIMITS[kind]).amount


def check_caller_rate_limit(kind: str, *, cost: int = 1) -> None:
    """Charge ``cost`` units to the ``kind`` budget ("search" or "ai") for the current caller.

    Raises McpRateLimitExceeded when the caller is over its limit.
    """
    if cost < 1:
        raise ValueError("MCP rate limit cost must be positive")
    limit_string = _LIMITS[kind]
    caller = _caller()
    if not _limiter.hit(parse(limit_string), "mcp", kind, caller, cost=cost):
        logger.warning("MCP rate limit exceeded: kind=%s caller=%s", kind, caller)
        raise McpRateLimitExceeded(
            f"Rate limit exceeded ({limit_string} for {kind}). Try again shortly."
        )
