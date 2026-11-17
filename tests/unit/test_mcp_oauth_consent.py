"""MCP OAuth: the consent step is tied to the browser that started the flow.

Before this, anyone could start an authorization, send a signed-in person the
link, and receive a code for that person's account; the resulting token also
worked on the main API. These tests drive the real MCP HTTP app.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest

from mcp_server import oauth
from mcp_server.http_server import MCPApp
from mcp_server.oauth import FLOW_COOKIE

REDIRECT = "http://127.0.0.1:9999/cb"
SECRET = secrets.token_urlsafe(48)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)
    monkeypatch.setattr(oauth, "AUTH_SECRET", SECRET)
    oauth._clients.clear()
    oauth._auth_codes.clear()
    oauth._rate_counts.clear()
    yield
    oauth._clients.clear()
    oauth._auth_codes.clear()
    oauth._rate_counts.clear()


def _app_origin() -> str:
    """The site the consent form is posted from (APP_BASE_URL's origin)."""
    parsed = urlparse(oauth._APP_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _session(user_id: str) -> str:
    """A web sign-in session cookie as the main app issues it."""
    return jwt.encode(
        {"sub": user_id, "aud": ["fastapi-users:auth"], "exp": int(time.time()) + 600},
        SECRET,
        algorithm="HS256",
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPApp()), base_url="http://mcp"
    )


async def _start_flow(client, client_name="Test client"):
    """Register a client and call /authorize, as the user's browser would."""
    reg = await client.post(
        "/register", json={"client_name": client_name, "redirect_uris": [REDIRECT]}
    )
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    auth = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st-1",
        },
    )
    assert auth.status_code == 302
    pending = parse_qs(urlparse(auth.headers["location"]).query)["mcp_auth"][0]
    set_cookie = auth.headers["set-cookie"]
    assert set_cookie.startswith(f"{FLOW_COOKIE}=")
    assert "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie
    flow = set_cookie.split(";", 1)[0].split("=", 1)[1]
    return pending, flow, verifier


def _cookies(session=None, flow=None) -> dict:
    parts = []
    if session:
        parts.append(f"evidencelab_auth={session}")
    if flow:
        parts.append(f"{FLOW_COOKIE}={flow}")
    return {"cookie": "; ".join(parts)} if parts else {}


def _consent_token(page: str) -> str:
    marker = "name='consent' value='"
    start = page.index(marker) + len(marker)
    return page[start : page.index("'", start)]


@pytest.mark.asyncio
async def test_flow_when_same_browser_allows_then_mcp_token_issued():
    async with _client() as client:
        pending, flow, verifier = await _start_flow(client)
        cookies = _cookies(_session("user-1"), flow)

        page = await client.get(
            "/complete", params={"pending": pending}, headers=cookies
        )
        assert page.status_code == 200
        assert "Allow this app?" in page.text and "127.0.0.1:9999" in page.text

        answer = await client.post(
            "/complete",
            data={
                "pending": pending,
                "consent": _consent_token(page.text),
                "decision": "allow",
            },
            headers={**cookies, "origin": _app_origin()},
        )
        assert answer.status_code == 302
        location = urlparse(answer.headers["location"])
        query = parse_qs(location.query)
        assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
        assert query["state"] == ["st-1"]
        assert "Max-Age=0" in answer.headers["set-cookie"]

        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200
        access = token.json()["access_token"]

    claims = jwt.decode(
        access, SECRET, algorithms=["HS256"], audience="evidencelab:mcp"
    )
    assert claims["sub"] == "user-1"


@pytest.mark.asyncio
async def test_complete_when_other_browser_opens_link_then_refused():
    """The victim is signed in, but did not start this flow: no flow cookie."""
    async with _client() as client:
        pending, _attacker_flow, _ = await _start_flow(client)
        victim = _cookies(_session("victim"))

        page = await client.get(
            "/complete", params={"pending": pending}, headers=victim
        )
        assert page.status_code == 403
        assert "different browser" in page.text

        answer = await client.post(
            "/complete",
            data={"pending": pending, "consent": "x", "decision": "allow"},
            headers={**victim, "origin": _app_origin()},
        )
        assert answer.status_code == 403
        assert "location" not in answer.headers


@pytest.mark.asyncio
async def test_complete_post_when_from_another_site_then_refused():
    async with _client() as client:
        pending, flow, _ = await _start_flow(client)
        cookies = _cookies(_session("user-1"), flow)
        page = await client.get(
            "/complete", params={"pending": pending}, headers=cookies
        )

        answer = await client.post(
            "/complete",
            data={
                "pending": pending,
                "consent": _consent_token(page.text),
                "decision": "allow",
            },
            headers={**cookies, "origin": "https://attacker.example"},
        )
        assert answer.status_code == 403


@pytest.mark.asyncio
async def test_complete_post_when_consent_token_wrong_then_refused():
    async with _client() as client:
        pending, flow, _ = await _start_flow(client)
        answer = await client.post(
            "/complete",
            data={"pending": pending, "consent": "guess", "decision": "allow"},
            headers={**_cookies(_session("user-1"), flow), "origin": _app_origin()},
        )
        assert answer.status_code == 400
        assert "location" not in answer.headers


@pytest.mark.asyncio
async def test_complete_when_user_denies_then_client_gets_access_denied():
    async with _client() as client:
        pending, flow, _ = await _start_flow(client)
        cookies = _cookies(_session("user-1"), flow)
        page = await client.get(
            "/complete", params={"pending": pending}, headers=cookies
        )

        answer = await client.post(
            "/complete",
            data={
                "pending": pending,
                "consent": _consent_token(page.text),
                "decision": "deny",
            },
            headers={**cookies, "origin": _app_origin()},
        )
        query = parse_qs(urlparse(answer.headers["location"]).query)
        assert query["error"] == ["access_denied"]
        assert "code" not in query


@pytest.mark.asyncio
async def test_complete_when_not_signed_in_then_sent_to_sign_in():
    async with _client() as client:
        pending, flow, _ = await _start_flow(client)
        page = await client.get(
            "/complete", params={"pending": pending}, headers=_cookies(flow=flow)
        )
        assert page.status_code == 302
        assert page.headers["location"] == f"{oauth._APP_BASE_URL}?mcp_auth={pending}"

        answer = await client.post(
            "/complete",
            data={"pending": pending, "consent": "x", "decision": "allow"},
            headers={**_cookies(flow=flow), "origin": _app_origin()},
        )
        assert answer.status_code == 401


@pytest.mark.asyncio
async def test_complete_when_mcp_token_used_as_session_then_not_signed_in():
    """Only a web session answers the consent page, not an MCP token."""
    async with _client() as client:
        pending, flow, _ = await _start_flow(client)
        mcp_token = jwt.encode(
            {"sub": "u", "aud": ["evidencelab:mcp"], "exp": int(time.time()) + 600},
            SECRET,
            algorithm="HS256",
        )
        page = await client.get(
            "/complete",
            params={"pending": pending},
            headers=_cookies(mcp_token, flow),
        )
        assert page.status_code == 302


@pytest.mark.asyncio
async def test_consent_page_when_client_name_has_markup_then_escaped():
    async with _client() as client:
        pending, flow, _ = await _start_flow(client, client_name="<script>x</script>")
        page = await client.get(
            "/complete",
            params={"pending": pending},
            headers=_cookies(_session("user-1"), flow),
        )
        assert "<script>x</script>" not in page.text
        assert "&lt;script&gt;" in page.text


def test_main_api_when_given_mcp_token_then_not_a_session():
    """The main API's session check refuses a token issued by the MCP flow."""
    from unittest.mock import AsyncMock

    from ui.backend.auth.active_auth import ActiveAuthMiddleware

    mcp_token = jwt.encode(
        {"sub": "u", "aud": ["evidencelab:mcp"], "exp": int(time.time()) + 600},
        SECRET,
        algorithm="HS256",
    )
    middleware = ActiveAuthMiddleware(AsyncMock(), auth_secret=SECRET)
    assert middleware._has_valid_jwt(mcp_token) is False
    assert middleware._has_valid_jwt(_session("u")) is True


@pytest.mark.asyncio
async def test_mcp_when_given_its_own_token_then_accepted():
    from starlette.requests import Request

    from mcp_server.auth import verify_mcp_auth

    mcp_token = jwt.encode(
        {"sub": "user-9", "aud": ["evidencelab:mcp"], "exp": int(time.time()) + 600},
        SECRET,
        algorithm="HS256",
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {mcp_token}".encode())],
    }
    info = await verify_mcp_auth(Request(scope))
    assert info["user_id"] == "user-9"
