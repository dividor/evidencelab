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

from a2a_server.app import handle_a2a_request, handle_agent_card
from mcp_server.app import mcp as mcp_server
from mcp_server.audit import request_auth, request_client_ip
from mcp_server.auth import verify_mcp_auth
from mcp_server.consent import (
    flow_cookie_header,
    handle_complete_get,
    handle_complete_post,
)
from mcp_server.oauth import (
    MAX_REGISTRATION_BYTES,
    build_authorize_redirect,
    exchange_token,
    get_metadata,
    public_mcp_url,
    register_client,
)
from ui.backend.services.ai_daily_limit import validate_ai_daily_limit_setting
from ui.backend.utils.llm_footprint import validate_footprint_settings

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
    """Extract the real client IP from the ASGI scope.

    Priority order:
    1. ``X-Real-IP`` — set by nginx to ``$remote_addr`` (the IP of the
       directly-connected client, cannot be spoofed by end users).
    2. The *rightmost* value in ``X-Forwarded-For`` — added by the nearest
       trusted reverse proxy (nginx/Caddy), so it reflects the last hop the
       request passed through under our control.  The leftmost entries can be
       set by the client and must not be trusted for security purposes.
    3. The ASGI ``client`` tuple as a last resort (direct connection).

    Never use the *first* (leftmost) ``X-Forwarded-For`` entry for auth or
    rate-limiting decisions — it is client-controlled and trivially spoofable.
    """
    headers = dict(scope.get("headers", []))

    # X-Real-IP is set by nginx to $remote_addr — cannot be spoofed by clients
    real_ip = headers.get(b"x-real-ip", b"").decode().strip()
    if real_ip:
        return real_ip

    # Fall back to the rightmost X-Forwarded-For entry (our trusted proxy)
    forwarded = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        if ips:
            return ips[-1]  # rightmost = set by our proxy, not the client

    client = scope.get("client")
    return client[0] if client else "unknown"


async def _read_body_up_to(request: Request, limit: int) -> bytes | None:
    """The request's body, or None as soon as it is known to exceed *limit* bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


def _parse_registration(raw: bytes) -> object:
    """The registration request's JSON; None when it isn't JSON (then refused)."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def _handle_register(scope, receive, send) -> None:
    """Dynamic client registration (RFC 7591), reading at most MAX_REGISTRATION_BYTES."""
    raw = await _read_body_up_to(Request(scope, receive), MAX_REGISTRATION_BYTES)
    if raw is None:
        status_code, result = 413, {
            "error": "invalid_client_metadata",
            "error_description": (
                f"The registration request is larger than {MAX_REGISTRATION_BYTES} bytes"
            ),
        }
    else:
        status_code, result = register_client(
            _parse_registration(raw), _get_client_ip(scope)
        )
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
    await send({"type": "http.response.body", "body": json.dumps(result).encode()})


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
            resource_url = public_mcp_url()
            resource_meta = {
                "resource": resource_url,
                "authorization_servers": [resource_url],
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
            await _handle_register(scope, receive, send)
            return

        # Authorization endpoint (GET)
        if path == "/authorize" and method == "GET":
            qs = scope.get("query_string", b"").decode()
            from urllib.parse import parse_qs

            params = {k: v[0] for k, v in parse_qs(qs).items()}
            client_ip = _get_client_ip(scope)
            status_code, redirect_url, flow_secret = build_authorize_redirect(
                params, client_ip
            )
            if status_code == 302 and flow_secret:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 302,
                        "headers": [
                            (b"location", redirect_url.encode()),
                            (b"cache-control", b"no-store"),
                            (b"set-cookie", flow_cookie_header(flow_secret)),
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

        # Consent step after sign-in: GET shows the page, POST records the answer
        if path == "/complete" and method == "GET":
            await handle_complete_get(scope, receive, send)
            return
        if path == "/complete" and method == "POST":
            await handle_complete_post(scope, receive, send)
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

        # A2A Agent Card
        if (
            path in ("/.well-known/agent.json", "/.well-known/agent-card.json")
            and method == "GET"
        ):
            await handle_agent_card(send)
            return

        # A2A JSON-RPC task endpoint
        if path in ("/a2a", "/a2a/") and method == "POST":
            a2a_auth_info: dict = {}
            a2a_principal: str | None = None
            if REQUIRE_AUTH:
                request = Request(scope, receive)
                try:
                    a2a_auth_info = await verify_mcp_auth(request)
                    a2a_principal = a2a_auth_info.get("user_id")
                    # Mirror the MCP branch: expose the caller's identity via
                    # the per-request auth context so token-usage recording
                    # (mcp_server.tools.assistant.record_assistant_usage)
                    # attributes A2A spend to the real API identity.
                    request_auth.set(
                        a2a_auth_info or {"type": "unknown", "user_id": "unknown"}
                    )
                    request_client_ip.set(_get_client_ip(scope))
                except PermissionError as exc:
                    logger.warning("A2A auth DENIED: %s", exc)
                    body = json.dumps({"detail": str(exc)}).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 401,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
            await handle_a2a_request(
                scope,
                receive,
                send,
                principal=a2a_principal,
                auth_info=a2a_auth_info,
                client_ip=_get_client_ip(scope),
            )
            return

        # MCP endpoint
        if path in ("/mcp", "/mcp/"):
            # Log incoming request details
            req_headers = dict(scope.get("headers", []))
            auth_hdr = req_headers.get(b"authorization", b"")
            api_key_hdr = req_headers.get(b"x-api-key", b"").decode()
            content_type = req_headers.get(b"content-type", b"").decode()
            logger.info(
                "MCP %s %s | auth=%r api_key=%s content_type=%s",
                method,
                scope.get("path", ""),
                "present" if auth_hdr else "absent",
                "present" if api_key_hdr else "absent",
                content_type,
            )

            # Auth check
            if REQUIRE_AUTH:
                request = Request(scope, receive)
                try:
                    principal = await verify_mcp_auth(request)
                    request_auth.set(
                        principal or {"type": "unknown", "user_id": "unknown"}
                    )
                    request_client_ip.set(_get_client_ip(scope))
                    logger.info("MCP auth OK: %s", principal)
                except PermissionError as exc:
                    logger.warning("MCP auth DENIED: %s", exc)
                    body = json.dumps({"detail": str(exc)}).encode()
                    origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
                    # Return 401 with WWW-Authenticate to trigger
                    # the client's OAuth discovery flow (MCP spec).
                    resource_url = public_mcp_url().rstrip("/")
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
            # A malformed daily AI limit stops the server here, not at the
            # first assistant call.
            validate_ai_daily_limit_setting()
            validate_footprint_settings()
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
