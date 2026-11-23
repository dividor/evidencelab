"""The consent step of the MCP OAuth flow (``/mcp/complete``).

``GET /mcp/complete?pending=...`` is reached after the person signs in to
Evidence Lab. It shows which client is asking and where it will be sent, and
asks them to allow or deny. ``POST /mcp/complete`` records the answer.

Both require a web session in this browser and the flow cookie set by
``/mcp/authorize`` in the browser that started the request, so a link to
someone else's pending request cannot be completed by a victim. The POST also
carries the page's one-time consent token and is refused from another origin.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request

from mcp_server import oauth
from mcp_server.auth import session_user_id
from mcp_server.oauth import (
    FLOW_COOKIE,
    FLOW_LIFETIME,
    complete_authorize,
    consent_details,
)

Send = Callable[[dict], Awaitable[None]]

_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "false"
_MAX_FORM_BYTES = 4096


def flow_cookie_header(value: str, max_age: int = FLOW_LIFETIME) -> bytes:
    """Set-Cookie value for the flow cookie (``max_age=0`` clears it)."""
    parts = [
        f"{FLOW_COOKIE}={value}",
        "Path=/mcp",
        f"Max-Age={max_age}",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if _COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts).encode()


def _app_origin() -> str:
    parsed = urlparse(oauth._APP_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title></head>"
        "<body style='font-family:system-ui,sans-serif;max-width:32rem;"
        "margin:4rem auto;padding:0 1rem;line-height:1.5;color:#1f2937'>"
        f"<h1 style='font-size:1.4rem'>{html.escape(title)}</h1>{body}</body></html>"
    )


def consent_page(details: dict, pending_id: str) -> str:
    """The allow/deny page. Every value from the request is escaped."""
    name = html.escape(details["client_name"])
    host = html.escape(details["redirect_host"])
    button = (
        "padding:.6rem 1.2rem;border-radius:6px;font-size:1rem;cursor:pointer;"
        "margin-right:.5rem;"
    )
    body = (
        f"<p><strong>{name}</strong> wants to use Evidence Lab with your account.</p>"
        f"<p>If you allow it, you will be sent back to <strong>{host}</strong>, and "
        "the app can search and read documents as you for the next hour.</p>"
        "<p>Only allow this if you started connecting this app yourself.</p>"
        "<form method='post' action='/mcp/complete'>"
        f"<input type='hidden' name='pending' value='{html.escape(pending_id)}'>"
        "<input type='hidden' name='consent' "
        f"value='{html.escape(details['consent_token'])}'>"
        "<button type='submit' name='decision' value='allow' "
        f"style='{button}background:#1a73e8;color:#fff;border:0'>Allow</button>"
        "<button type='submit' name='decision' value='deny' "
        f"style='{button}background:#fff;border:1px solid #9ca3af'>Deny</button>"
        "</form>"
    )
    return _page("Allow this app?", body)


async def _send(
    send: Send, status: int, body: bytes, headers: list[tuple[bytes, bytes]]
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"cache-control", b"no-store"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_page(send: Send, status: int, title: str, message: str) -> None:
    page = _page(title, f"<p>{html.escape(message)}</p>")
    await _send(
        send, status, page.encode(), [(b"content-type", b"text/html; charset=utf-8")]
    )


def _error_message(body: str) -> str:
    try:
        return str(json.loads(body).get("error_description") or "Request refused")
    except ValueError:
        return "Request refused"


async def handle_complete_get(scope: dict, receive: Any, send: Send) -> None:
    """Show the consent page, or send the person to sign in first."""
    request = Request(scope, receive)
    pending_id = request.query_params.get("pending", "")
    if not pending_id:
        await _send_page(send, 400, "Request incomplete", "Missing pending parameter.")
        return
    if session_user_id(request) is None:
        login_url = f"{oauth._APP_BASE_URL}?mcp_auth={pending_id}"
        await _send(send, 302, b"", [(b"location", login_url.encode())])
        return
    status, details = consent_details(pending_id, request.cookies.get(FLOW_COOKIE))
    if status != 200 or not isinstance(details, dict):
        await _send_page(send, status, "Cannot connect", _error_message(str(details)))
        return
    page = consent_page(details, pending_id)
    await _send(
        send, 200, page.encode(), [(b"content-type", b"text/html; charset=utf-8")]
    )


async def handle_complete_post(scope: dict, receive: Any, send: Send) -> None:
    """Record the allow/deny answer and send the browser back to the client."""
    request = Request(scope, receive)
    origin = request.headers.get("origin")
    if origin and origin != _app_origin():
        await _send_page(send, 403, "Cannot connect", "Request from another site.")
        return
    user_id = session_user_id(request)
    if user_id is None:
        await _send_page(send, 401, "Cannot connect", "Sign in to Evidence Lab first.")
        return
    raw = await request.body()
    if len(raw) > _MAX_FORM_BYTES:
        await _send_page(send, 413, "Cannot connect", "Request too large.")
        return
    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    status, result = complete_authorize(
        form.get("pending", ""),
        user_id,
        request.cookies.get(FLOW_COOKIE),
        form.get("consent", ""),
        approved=form.get("decision") == "allow",
    )
    if status != 302:
        await _send_page(send, status, "Cannot connect", _error_message(result))
        return
    await _send(
        send,
        302,
        b"",
        [
            (b"location", result.encode()),
            (b"set-cookie", flow_cookie_header("", max_age=0)),
        ],
    )
