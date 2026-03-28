"""HTTP server for Evidence Lab MCP with SSE transport.

Runs as a separate FastAPI application on port 8001.  Uses the
official ``mcp`` SDK's SSE transport to serve MCP clients (Cursor,
Claude Desktop, etc.).

Usage::

    python -m ui.backend.mcp.http_server
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.sse import SseServerTransport
from starlette.routing import Route

from ui.backend.mcp.auth import verify_mcp_auth

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUIRE_AUTH = True


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


async def _check_auth(request: Request) -> JSONResponse | None:
    """Return a 403 JSONResponse if auth fails, or ``None`` if OK."""
    if not REQUIRE_AUTH:
        return None
    try:
        await verify_mcp_auth(request)
        return None
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# SSE transport — the /messages/ path must match the POST route
# ---------------------------------------------------------------------------

sse_transport = SseServerTransport("/messages/")


# ---------------------------------------------------------------------------
# ASGI-level route handlers (SSE transport needs raw scope/receive/send)
# ---------------------------------------------------------------------------


async def handle_sse_get(scope, receive, send):
    """GET /sse -- establish the SSE connection for MCP clients."""
    request = Request(scope, receive)
    auth_err = await _check_auth(request)
    if auth_err is not None:
        await auth_err(scope, receive, send)
        return

    from ui.backend.mcp.server import mcp as mcp_server

    async with sse_transport.connect_sse(scope, receive, send) as streams:
        await mcp_server._mcp_server.run(
            streams[0],
            streams[1],
            mcp_server._mcp_server.create_initialization_options(),
        )


async def handle_messages(scope, receive, send):
    """POST /messages/ -- receive JSON-RPC messages from MCP clients."""
    request = Request(scope, receive)
    auth_err = await _check_auth(request)
    if auth_err is not None:
        await auth_err(scope, receive, send)
        return

    await sse_transport.handle_post_message(scope, receive, send)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan context manager."""
    logger.info("MCP SSE server starting")
    yield
    logger.info("MCP SSE server shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Evidence Lab MCP Server",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chatgpt.com",
        "https://claude.ai",
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check (standard FastAPI route)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "mcp"}


# ---------------------------------------------------------------------------
# Mount SSE routes as raw Starlette routes (they need ASGI scope/receive/send)
# ---------------------------------------------------------------------------

app.routes.append(Route("/sse", endpoint=handle_sse_get, methods=["GET"]))
app.routes.append(Route("/messages/", endpoint=handle_messages, methods=["POST"]))
app.routes.append(Route("/messages", endpoint=handle_messages, methods=["POST"]))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _configure():
    """Read environment and configure module-level settings."""
    global REQUIRE_AUTH  # noqa: PLW0603

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,
    )

    REQUIRE_AUTH = os.environ.get("REQUIRE_API_KEY", "true").lower() == "true"


if __name__ == "__main__":
    _configure()

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8001"))
    logger.info("Starting MCP SSE server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, access_log=True)
