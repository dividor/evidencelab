"""HTTP server for Evidence Lab MCP with Streamable HTTP transport.

Runs as a separate application on port 8001.  Uses the official ``mcp``
SDK's Streamable HTTP transport to serve MCP clients (Claude Desktop,
Claude Code, ChatGPT, MCP Inspector, etc.).

Usage::

    python -m ui.backend.mcp.http_server
"""

from __future__ import annotations

import json
import logging
import os

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request

from ui.backend.mcp.auth import verify_mcp_auth
from ui.backend.mcp.server import mcp as mcp_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUIRE_AUTH = os.environ.get("REQUIRE_API_KEY", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

session_manager = StreamableHTTPSessionManager(
    app=mcp_server._mcp_server,
    json_response=True,
    stateless=True,
)

# ---------------------------------------------------------------------------
# CORS headers
# ---------------------------------------------------------------------------

CORS_ORIGINS = {
    "https://chatgpt.com",
    "https://chat.openai.com",
    "https://claude.ai",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8001",
}


def _add_cors_headers(headers: list, origin: str | None) -> list:
    """Add CORS headers if the origin is allowed."""
    if origin and origin in CORS_ORIGINS:
        headers.extend(
            [
                (b"access-control-allow-origin", origin.encode()),
                (b"access-control-allow-credentials", b"true"),
                (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
                (
                    b"access-control-allow-headers",
                    b"Content-Type, Authorization, X-API-Key, Accept, Mcp-Session-Id",
                ),
            ]
        )
    return headers


# ---------------------------------------------------------------------------
# Raw ASGI application
# ---------------------------------------------------------------------------


class MCPApp:
    """Minimal ASGI app that routes /mcp to the session manager."""

    def __init__(self):
        self._started = False

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] != "http":
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # CORS preflight
        if method == "OPTIONS":
            origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
            headers = _add_cors_headers([], origin)
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": headers,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        # Health check
        if path == "/health":
            body = json.dumps({"status": "ok", "service": "mcp"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # MCP endpoint
        if path in ("/mcp", "/mcp/"):
            # Auth check
            if REQUIRE_AUTH:
                request = Request(scope, receive)
                try:
                    await verify_mcp_auth(request)
                except PermissionError as exc:
                    body = json.dumps({"detail": str(exc)}).encode()
                    origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
                    headers = _add_cors_headers(
                        [(b"content-type", b"application/json")], origin
                    )
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": headers,
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return

            # Add CORS headers to MCP responses
            origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()

            async def cors_send(message):
                if message["type"] == "http.response.start":
                    message = dict(message)
                    message["headers"] = _add_cors_headers(
                        list(message.get("headers", [])), origin
                    )
                await send(message)

            await session_manager.handle_request(scope, receive, cors_send)
            return

        # 404 for everything else
        body = json.dumps({"detail": "Not Found"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _handle_lifespan(self, scope, receive, send):
        """Handle ASGI lifespan events — start/stop session manager."""
        message = await receive()
        if message["type"] != "lifespan.startup":
            return

        try:
            self._cm = session_manager.run()
            await self._cm.__aenter__()
            self._started = True
            logger.info("StreamableHTTP session manager started")
            await send({"type": "lifespan.startup.complete"})
        except Exception as exc:
            logger.error("MCP startup failed: %s", exc)
            await send({"type": "lifespan.startup.failed", "message": str(exc)})
            return

        # Wait for shutdown
        message = await receive()
        if message["type"] == "lifespan.shutdown":
            if self._started:
                await self._cm.__aexit__(None, None, None)
                logger.info("StreamableHTTP session manager stopped")
            await send({"type": "lifespan.shutdown.complete"})


app = MCPApp()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,
    )

    REQUIRE_AUTH = os.environ.get("REQUIRE_API_KEY", "true").lower() == "true"

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8001"))
    logger.info("Starting MCP HTTP server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, access_log=True)
