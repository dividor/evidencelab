"""A2A ASGI request handler for Evidence Lab.

Handles:
  GET  /.well-known/agent.json   — Agent Card discovery
  POST /a2a                      — JSON-RPC task endpoint

Registered in mcp_server/http_server.py alongside the MCP routes.
"""

from __future__ import annotations

import json
import logging
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

# In-memory task store (task_id → Task).
# Tasks are short-lived; this is sufficient for stateless deployments.
_tasks: Dict[str, Task] = {}
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


async def handle_a2a_request(scope, receive, send) -> None:
    """Handle POST /a2a — JSON-RPC task endpoint."""
    # Read body
    body_chunks = []
    more = True
    while more:
        msg = await receive()
        body_chunks.append(msg.get("body", b""))
        more = msg.get("more_body", False)
    raw = b"".join(body_chunks)

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
            await _handle_tasks_send(rpc_id, params, send)
        elif method in ("tasks/sendSubscribe", "message/stream"):
            await _handle_tasks_send_subscribe(rpc_id, params, scope, send)
        elif method == "tasks/get":
            await _handle_tasks_get(rpc_id, params, send)
        elif method == "tasks/cancel":
            await _handle_tasks_cancel(rpc_id, params, send)
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


async def _handle_tasks_send(rpc_id: Any, params: Any, send) -> None:
    """tasks/send / message/send — execute task and return completed Task."""
    try:
        send_params = TaskSendParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    # params.id (old spec) or fall back to rpc_id (new spec) or uuid
    task_id = send_params.id or (str(rpc_id) if rpc_id else None) or str(uuid.uuid4())
    task = await handle_task(task_id, send_params.message)
    _tasks[task_id] = task
    if len(_tasks) > _MAX_TASKS:
        oldest_key = next(iter(_tasks))
        del _tasks[oldest_key]

    response = JSONRPCResponse(id=rpc_id, result=task.model_dump(exclude_none=True))
    await _send_json(send, 200, response.model_dump(exclude_none=True))


async def _handle_tasks_send_subscribe(
    rpc_id: Any, params: Any, scope: dict, send
) -> None:
    """tasks/sendSubscribe / message/stream — stream task events as SSE."""
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

    async for sse_line in handle_task_streaming(task_id, send_params.message, rpc_id):
        await send(
            {"type": "http.response.body", "body": sse_line.encode(), "more_body": True}
        )

    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _handle_tasks_get(rpc_id: Any, params: Any, send) -> None:
    """tasks/get — retrieve a previously submitted task."""
    try:
        query_params = TaskQueryParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    task = _tasks.get(query_params.id)
    if task is None:
        await _send_error(
            send, rpc_id, A2A_TASK_NOT_FOUND, f"Task not found: {query_params.id}"
        )
        return

    response = JSONRPCResponse(id=rpc_id, result=task.model_dump(exclude_none=True))
    await _send_json(send, 200, response.model_dump(exclude_none=True))


async def _handle_tasks_cancel(rpc_id: Any, params: Any, send) -> None:
    """tasks/cancel — cancel a task (not supported for completed tasks)."""
    try:
        id_params = TaskIdParams.model_validate(params)
    except Exception as exc:
        await _send_error(send, rpc_id, JSONRPC_INVALID_PARAMS, str(exc))
        return

    task = _tasks.get(id_params.id)
    if task is None:
        await _send_error(
            send, rpc_id, A2A_TASK_NOT_FOUND, f"Task not found: {id_params.id}"
        )
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
    _tasks[id_params.id] = task

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
