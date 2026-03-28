"""Unit tests for MCP audit logging."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from mcp_server.audit import _do_log


@pytest.mark.asyncio
async def test_log_mcp_call_success(monkeypatch):
    """Verify the SQL insert is called with the correct positional parameters."""
    fake_pool = AsyncMock()
    fake_pool.execute = AsyncMock()

    import mcp_server.audit as audit_mod

    monkeypatch.setattr(audit_mod, "_get_pool", AsyncMock(return_value=fake_pool))

    auth_info = {"type": "api_key", "user_id": "env_key", "key_hash": "abc123"}

    await _do_log(
        tool_name="search",
        auth_info=auth_info,
        client_ip="127.0.0.1",
        input_params={"query": "test", "limit": 10},
        output_summary="status=ok",
        duration_ms=42.5,
        status="ok",
        error_message=None,
    )

    fake_pool.execute.assert_awaited_once()
    call_args = fake_pool.execute.call_args

    # Positional args after the SQL string
    params = call_args[0][1:]
    assert params[0] == "search"  # tool_name
    assert params[1] == "api_key"  # auth_type
    assert params[2] == "env_key"  # user_id
    assert params[3] == "abc123"  # key_hash
    assert params[4] == "127.0.0.1"  # client_ip
    parsed = json.loads(params[5])
    assert parsed["query"] == "test"  # input_params JSON
    assert params[6] == "status=ok"  # output_summary
    assert params[7] == 42.5  # duration_ms
    assert params[8] == "ok"  # status
    assert params[9] is None  # error_message


@pytest.mark.asyncio
async def test_log_mcp_call_handles_db_error(monkeypatch):
    """DB errors in audit logging are caught, not raised."""
    fake_pool = AsyncMock()
    fake_pool.execute = AsyncMock(side_effect=Exception("connection refused"))

    import mcp_server.audit as audit_mod

    monkeypatch.setattr(audit_mod, "_get_pool", AsyncMock(return_value=fake_pool))

    # Should not raise despite the DB error
    await _do_log(
        tool_name="search",
        auth_info={"type": "unknown", "user_id": ""},
        client_ip="unknown",
        input_params={},
        output_summary="status=error",
        duration_ms=0.0,
        status="error",
        error_message="some error",
    )
    # If we reach here, the exception was caught correctly
    fake_pool.execute.assert_awaited_once()
