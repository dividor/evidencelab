"""A2A ASGI request handler for Evidence Lab.

Handles:
  GET  /.well-known/agent.json   — Agent Card discovery
  POST /a2a                      — JSON-RPC task endpoint

Registered in mcp_server/http_server.py alongside the MCP routes.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict

from a2a_server.agent_card import build_agent_card
from a2a_server.schemas import (
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TaskState,
    TaskStatus,
)
from a2a_server.task_handler import handle_task, handle_task_streaming

logger = logging.getLogger(__name__)

# In-memory task store: task_id → (Task, principal).
# Tasks are short-lived; this is sufficient for stateless deployments.
# The principal (authenticated user_id) is stored alongside each task so that
# tasks/get and tasks/cancel can enforce ownership — preventing one caller from
# reading or cancelling another caller's results.
_tasks: Dict[str, tuple[Task, str | None]] = {}
_MAX_TASKS = 1000


# ---------------------------------------------------------------------------
# Public route handlers (called from mcp_server/http_server.py)
# ---------------------------------------------------------------------------


async def handle_agent_card(send) -> None:
    """Serve GET /.well-known/agent.json."""
    card = build_agent_card()
    body = card.model_dump_json(exclude_none=True).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"public, max-age=3600"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def handle_a2a_request(
    scope,
    receive,
    send,
    principal: str | None = None,
    auth_info: Dict[str, Any] | None = None,
    client_ip: str = "",
) -> None:
    """Handle POST /a2a — JSON-RPC task endpoint.

    ``auth_info`` and ``client_ip`` are forwarded to audit logging so that
    each task execution is recorded in ``mcp_audit_log`` with protocol='a2a'.
    ``principal`` is the authenticated user_id from ``verify_mcp_auth``; it is
    stored with every new task and checked on reads/cancels to enforce ownership.
    """
    # Read body
    body_chunks = []
    more = True
    while more:
        msg = await receive()
        body_chunks.append(msg.get("body", b""))
        more = msg.get("more_body", False)
    raw = b"".join(body_chunks)

    _auth = auth_info or {}

    # Parse JSON-RPC envelope
    try:
        payload = json.loads(raw)
    except Exception:
        await _send_error(send, None, JSONRPC_PARSE_ERROR, "Parse error")
        return

    try:
        rpc = JSONRPCRequest.model_validate(payload)
    except Exception:
        await _send_error(send, None, JSONRPC_INVALID_REQUEST, "Invalid request")
        return

    rpc_id = rpc.id
    method = rpc.method
    params = rpc.params or {}

    logger.info("A2A RPC id=%s method=%s", rpc_id, method)

    try:
        # Support both old spec (tasks/*) and new spec (message/*) method names
        if method in ("tasks/send", "message/send"):
            await _handle_tasks_send(
                rpc_id, params, send, method, _auth, client_ip, principal
            )
        elif method in ("tasks/sendSubscribe", "message/stream"):
            await _handle_tasks_send_subscribe(
                rpc_id, params, scope, send, method, _auth, client_ip, principal
            )
        elif method == "tasks/get":
            await _handle_tasks_get(rpc_id, params, send, principal)
        elif method == "tasks/cancel":
            await _handle_tasks_cancel(rpc_id, params, send, principal)
        else:
            await _send_error(
                send, rpc_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}"
            )
    except Exception as exc:
        logger.exception("A2A unhandled error for %s: %s", method, exc)
        await _send_error(send, rpc_id, JSONRPC_INTERNAL_ERROR, str(exc))


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------


async def _handle_tasks_send(
    rpc_id: Any,
    params: Any,
    send,
    method: str = "tasks/send",
    auth_info: Dict[str, Any] | None = None,
    client_ip: str = "",
    principal: str | None = None,
) -> None:
    """tasks/send / message/send — execute task and return completed Task."""
    from mcp_server.audit import log_mcp_call

    try:
        send_params = TaskSendParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    # params.id (old spec) or fall back to rpc_id (new spec) or uuid
    task_id = send_params.id or (str(rpc_id) if rpc_id else None) or str(uuid.uuid4())
    t0 = time.monotonic()
    task = await handle_task(task_id, send_params.message)
    duration_ms = (time.monotonic() - t0) * 1000

    _tasks[task_id] = (task, principal)
    if len(_tasks) > _MAX_TASKS:
        oldest_key = next(iter(_tasks))
        del _tasks[oldest_key]

    state = task.status.state.value if task.status else "unknown"
    first_text = next(
        (p.text for p in (send_params.message.parts or []) if hasattr(p, "text")),
        "",
    )
    log_mcp_call(
        tool_name=method,
        auth_info=auth_info or {},
        client_ip=client_ip,
        input_params={
            "query": first_text[:500],
            "data_source": (send_params.message.metadata or {}).get("data_source"),
        },
        output_summary=json.dumps(task.model_dump(exclude_none=True)),
        duration_ms=duration_ms,
        status="ok" if state == "completed" else "error",
        protocol="a2a",
    )

    response = JSONRPCResponse(id=rpc_id, result=task.model_dump(exclude_none=True))
    await _send_json(send, 200, response.model_dump(exclude_none=True))


async def _handle_tasks_send_subscribe(
    rpc_id: Any,
    params: Any,
    scope: dict,
    send,
    method: str = "tasks/sendSubscribe",
    auth_info: Dict[str, Any] | None = None,
    client_ip: str = "",
    principal: str | None = None,
) -> None:
    """tasks/sendSubscribe / message/stream — stream task events as SSE."""
    from mcp_server.audit import log_mcp_call

    try:
        send_params = TaskSendParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    # Check the client accepts SSE
    req_headers = dict(scope.get("headers", []))
    accept = req_headers.get(b"accept", b"").decode()
    if "text/event-stream" not in accept:
        await _send_error(
            send,
            rpc_id,
            A2A_UNSUPPORTED_OPERATION,
            "Client must accept text/event-stream for tasks/sendSubscribe",
        )
        return

    task_id = send_params.id or (str(rpc_id) if rpc_id else None) or str(uuid.uuid4())

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream; charset=utf-8"),
                (b"cache-control", b"no-cache"),
                (b"x-accel-buffering", b"no"),
            ],
        }
    )

    t0 = time.monotonic()
    async for sse_line in handle_task_streaming(task_id, send_params.message, rpc_id):
        await send(
            {"type": "http.response.body", "body": sse_line.encode(), "more_body": True}
        )
    duration_ms = (time.monotonic() - t0) * 1000

    await send({"type": "http.response.body", "body": b"", "more_body": False})

    first_text = next(
        (p.text for p in (send_params.message.parts or []) if hasattr(p, "text")),
        "",
    )
    log_mcp_call(
        tool_name=method,
        auth_info=auth_info or {},
        client_ip=client_ip,
        input_params={
            "query": first_text[:500],
            "data_source": (send_params.message.metadata or {}).get("data_source"),
        },
        output_summary=(
            json.dumps(_tasks[task_id][0].model_dump(exclude_none=True))
            if task_id in _tasks
            else "streamed"
        ),
        duration_ms=duration_ms,
        status="ok",
        protocol="a2a",
    )


def _check_task_ownership(
    entry: tuple[Task, str | None] | None,
    task_id: str,
    principal: str | None,
) -> tuple[Task | None, str | None]:
    """Return (task, error_message).

    Returns an error when the task does not exist or when ``principal`` does not
    own it.  Two principals are considered equal when either side is ``None``
    (auth disabled / legacy client) so that deployments without REQUIRE_AUTH
    still work correctly.
    """
    if entry is None:
        return None, f"Task not found: {task_id}"
    task, owner = entry
    if principal is not None and owner is not None and principal != owner:
        # Return the same "not found" message to avoid leaking that the task
        # exists but belongs to a different user.
        logger.warning(
            "A2A ownership mismatch: principal=%r owner=%r task=%s",
            principal,
            owner,
            task_id,
        )
        return None, f"Task not found: {task_id}"
    return task, None


async def _handle_tasks_get(
    rpc_id: Any, params: Any, send, principal: str | None
) -> None:
    """tasks/get — retrieve a previously submitted task."""
    try:
        query_params = TaskQueryParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    task, err = _check_task_ownership(
        _tasks.get(query_params.id), query_params.id, principal
    )
    if task is None:
        await _send_error(send, rpc_id, A2A_TASK_NOT_FOUND, err or "Task not found")
        return

    response = JSONRPCResponse(id=rpc_id, result=task.model_dump(exclude_none=True))
    await _send_json(send, 200, response.model_dump(exclude_none=True))


async def _handle_tasks_cancel(
    rpc_id: Any, params: Any, send, principal: str | None
) -> None:
    """tasks/cancel — cancel a task (not supported for completed tasks)."""
    try:
        id_params = TaskIdParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    task, err = _check_task_ownership(_tasks.get(id_params.id), id_params.id, principal)
    if task is None:
        await _send_error(send, rpc_id, A2A_TASK_NOT_FOUND, err or "Task not found")
        return

    if task.status.state == TaskState.COMPLETED:
        await _send_error(
            send,
            rpc_id,
            A2A_UNSUPPORTED_OPERATION,
            "Cannot cancel a completed task",
        )
        return

    from datetime import datetime, timezone

    task.status = TaskStatus(
        state=TaskState.CANCELED, timestamp=datetime.now(timezone.utc).isoformat()
    )
    _tasks[id_params.id] = (task, principal)

    response = JSONRPCResponse(id=rpc_id, result=task.model_dump(exclude_none=True))
    await _send_json(send, 200, response.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_json(send, status: int, data: dict) -> None:
    body = json.dumps(data).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_error(send, rpc_id: Any, code: int, message: str) -> None:
    response = JSONRPCResponse(
        id=rpc_id if rpc_id is not None else 0,
        error=JSONRPCError(code=code, message=message),
    )
    await _send_json(send, 200, response.model_dump(exclude_none=True))
