"""Fire-and-forget audit logging for MCP tool calls.

Inserts rows into the ``mcp_audit_log`` table using asyncpg for
non-blocking writes.  All errors are caught and logged so that
audit failures never break tool execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazy-initialised asyncpg connection pool
_pool = None


async def _get_pool():
    """Return (and lazily create) a shared asyncpg connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        return _pool

    try:
        import asyncpg

        host = os.getenv("POSTGRES_HOST", "localhost")
        if os.path.exists("/.dockerenv") and host in {"localhost", "127.0.0.1"}:
            host = "postgres"
        port = int(os.getenv("POSTGRES_PORT", "5432"))
        dbname = os.getenv("POSTGRES_DBNAME") or os.getenv("POSTGRES_DB", "evidencelab")
        user = os.getenv("POSTGRES_USER", "evidencelab")
        password = os.getenv("POSTGRES_PASSWORD", "evidencelab")

        _pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=dbname,
            user=user,
            password=password,
            min_size=1,
            max_size=3,
        )
        return _pool
    except Exception:
        logger.warning("Failed to create asyncpg pool for MCP audit", exc_info=True)
        return None


async def _do_log(
    tool_name: str,
    auth_info: Dict[str, Any],
    client_ip: str,
    input_params: Dict[str, Any],
    output_summary: str,
    duration_ms: float,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Insert a single audit row.  Meant to be run as a fire-and-forget task."""
    pool = await _get_pool()
    if pool is None:
        return

    try:
        await pool.execute(
            """
            INSERT INTO mcp_audit_log
                (tool_name, auth_type, user_id, key_hash,
                 client_ip, input_params, output_summary,
                 duration_ms, status, error_message)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            tool_name,
            auth_info.get("type", "unknown"),
            str(auth_info.get("user_id", "")),
            auth_info.get("key_hash"),
            client_ip,
            json.dumps(input_params, default=str),
            output_summary[:2000] if output_summary else "",
            duration_ms,
            status,
            error_message,
        )
    except Exception:
        logger.warning("MCP audit log insert failed", exc_info=True)


def log_mcp_call(
    tool_name: str,
    auth_info: Dict[str, Any],
    client_ip: str,
    input_params: Dict[str, Any],
    output_summary: str,
    duration_ms: float,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Schedule an audit log write as a fire-and-forget background task.

    Safe to call from any async context.  Exceptions inside the task
    are caught and logged, never propagated.
    """
    try:
        asyncio.create_task(
            _do_log(
                tool_name,
                auth_info,
                client_ip,
                input_params,
                output_summary,
                duration_ms,
                status,
                error_message,
            )
        )
    except RuntimeError:
        # No running event loop (e.g. during tests or shutdown)
        logger.debug("Could not schedule MCP audit log — no event loop")
