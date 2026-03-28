"""HTTP server for Evidence Lab MCP with Streamable HTTP transport.

Runs as a separate application on port 8001.  Uses the official ``mcp``
SDK's Streamable HTTP transport to serve MCP clients (Claude Desktop,
Claude Code, ChatGPT, MCP Inspector, etc.).

Usage::

    python -m mcp_server.http_server
"""

from __future__ import annotations

import json
import logging
import os

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request

from mcp_server.app import mcp as mcp_server
from mcp_server.auth import verify_mcp_auth
from mcp_server.oauth import (
    build_authorize_redirect,
    complete_authorize,
    exchange_token,
    get_metadata,
    register_client,
)

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


def _get_client_ip(scope: dict) -> str:
    """Extract client IP from ASGI scope, preferring X-Forwarded-For."""
    headers = dict(scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = headers.get(b"x-real-ip", b"").decode()
    if real_ip:
        return real_ip
    client = scope.get("client")
    return client[0] if client else "unknown"


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

        # When behind a reverse proxy at /mcp, requests arrive with
        # /mcp prefix (e.g. /mcp/.well-known/...).  Strip it so
        # route matching works the same both directly and proxied.
        if path.startswith("/mcp/"):
            path = path[4:]  # /mcp/foo -> /foo

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

        # Log all requests
        logger.info("REQUEST %s %s (original: %s)", method, path, scope.get("path", ""))

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

        # OAuth 2.0 Protected Resource Metadata (RFC 9728)
        if path == "/.well-known/oauth-protected-resource":
            base_url = os.environ.get("APP_BASE_URL", "https://evidencelab.ai")
            resource_meta = {
                "resource": f"{base_url}/mcp",
                "authorization_servers": [f"{base_url}/mcp"],
                "bearer_methods_supported": ["header"],
            }
            body = json.dumps(resource_meta).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # OpenID Connect discovery (Claude checks this)
        if path == "/.well-known/openid-configuration":
            meta = get_metadata()
            body = json.dumps(meta).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # OAuth 2.0 metadata discovery (RFC 8414)
        if path == "/.well-known/oauth-authorization-server":
            body = json.dumps(get_metadata()).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Dynamic client registration (RFC 7591)
        if path == "/register" and method == "POST":
            request = Request(scope, receive)
            req_body = await request.body()
            client_data = json.loads(req_body) if req_body else {}
            client_ip = _get_client_ip(scope)
            status_code, result = register_client(client_data, client_ip)
            body = json.dumps(result).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Authorization endpoint (GET)
        if path == "/authorize" and method == "GET":
            qs = scope.get("query_string", b"").decode()
            from urllib.parse import parse_qs

            params = {k: v[0] for k, v in parse_qs(qs).items()}
            client_ip = _get_client_ip(scope)
            status_code, redirect_url = build_authorize_redirect(params, client_ip)
            if status_code == 302:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 302,
                        "headers": [
                            (b"location", redirect_url.encode()),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": status_code,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": redirect_url.encode()}
                )
            return

        # Complete OAuth after user login (GET /complete?pending=...)
        if path == "/complete" and method == "GET":
            request = Request(scope, receive)
            qs = scope.get("query_string", b"").decode()
            from urllib.parse import parse_qs

            params = {k: v[0] for k, v in parse_qs(qs).items()}
            pending_id = params.get("pending", "")

            if not pending_id:
                body = json.dumps({"error": "Missing pending parameter"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

            # Verify the user is authenticated via session cookie or JWT
            try:
                auth_info = await verify_mcp_auth(request)
                user_id = auth_info.get("user_id", "unknown")
            except PermissionError:
                # Not logged in — redirect back to login page
                from mcp_server.oauth import _APP_BASE_URL

                login_url = f"{_APP_BASE_URL}?mcp_auth={pending_id}"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 302,
                        "headers": [
                            (b"location", login_url.encode()),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
                return

            status_code, redirect_url = complete_authorize(pending_id, user_id)
            if status_code == 302:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 302,
                        "headers": [
                            (b"location", redirect_url.encode()),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": status_code,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": redirect_url.encode()}
                )
            return

        # Token endpoint (POST)
        if path == "/token" and method == "POST":
            request = Request(scope, receive)
            req_body = await request.body()
            # Accept both JSON and form-encoded
            content_type = (
                dict(scope.get("headers", [])).get(b"content-type", b"").decode()
            )
            if "application/json" in content_type:
                token_data = json.loads(req_body) if req_body else {}
            else:
                from urllib.parse import parse_qs

                parsed = parse_qs(req_body.decode())
                token_data = {k: v[0] for k, v in parsed.items()}

            client_ip = _get_client_ip(scope)
            status_code, result = exchange_token(token_data, client_ip)
            body = json.dumps(result).encode()
            origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
            headers = _add_cors_headers(
                [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
                origin,
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": headers,
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # MCP endpoint
        if path in ("/mcp", "/mcp/"):
            # Log incoming request details
            req_headers = dict(scope.get("headers", []))
            auth_hdr = req_headers.get(b"authorization", b"").decode()
            api_key_hdr = req_headers.get(b"x-api-key", b"").decode()
            content_type = req_headers.get(b"content-type", b"").decode()
            logger.info(
                "MCP %s %s | auth=%r api_key=%s content_type=%s",
                method,
                scope.get("path", ""),
                auth_hdr[:40] + "..." if len(auth_hdr) > 40 else auth_hdr,
                "present" if api_key_hdr else "absent",
                content_type,
            )

            # Auth check
            if REQUIRE_AUTH:
                request = Request(scope, receive)
                try:
                    principal = await verify_mcp_auth(request)
                    logger.info("MCP auth OK: %s", principal)
                except PermissionError as exc:
                    logger.warning("MCP auth DENIED: %s", exc)
                    body = json.dumps({"detail": str(exc)}).encode()
                    origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
                    # Return 401 with WWW-Authenticate to trigger
                    # the client's OAuth discovery flow (MCP spec).
                    base_url = os.environ.get("APP_BASE_URL", "https://evidencelab.ai")
                    resource_url = f"{base_url}/mcp"
                    headers = _add_cors_headers(
                        [
                            (b"content-type", b"application/json"),
                            (
                                b"www-authenticate",
                                f"Bearer resource_metadata="
                                f'"{resource_url}/.well-known/'
                                f'oauth-protected-resource"'.encode(),
                            ),
                        ],
                        origin,
                    )
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 401,
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
