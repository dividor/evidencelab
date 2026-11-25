"""MCP dynamic client registration keeps each registration small and their number capped.

Anyone can register a client and registrations live in the MCP server's
memory, so the request size, the metadata and the number kept are limited.
These tests drive the real MCP HTTP app.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest

from mcp_server import oauth
from mcp_server.http_server import MCPApp
from mcp_server.oauth import FLOW_COOKIE, MAX_REGISTRATION_BYTES

REDIRECT = "http://127.0.0.1:9999/cb"
SECRET = secrets.token_urlsafe(48)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    # The consent page checks the web session with the key from the environment.
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)
    monkeypatch.setattr(oauth, "AUTH_SECRET", SECRET)
    oauth._clients.clear()
    oauth._auth_codes.clear()
    oauth._rate_counts.clear()
    yield
    oauth._clients.clear()
    oauth._auth_codes.clear()
    oauth._rate_counts.clear()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPApp()), base_url="http://mcp"
    )


async def _register(client, **metadata) -> httpx.Response:
    return await client.post(
        "/register",
        json={"client_name": "Test client", "redirect_uris": [REDIRECT], **metadata},
    )


async def _get_token(client, client_id: str) -> None:
    """Take a registered client through authorize, consent and token, as a real one would."""
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
        },
    )
    pending = parse_qs(urlparse(auth.headers["location"]).query)["mcp_auth"][0]
    flow = auth.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    session = jwt.encode(
        {"sub": "user-1", "aud": ["fastapi-users:auth"], "exp": int(time.time()) + 600},
        SECRET,
        algorithm="HS256",
    )
    cookies = {"cookie": f"evidencelab_auth={session}; {FLOW_COOKIE}={flow}"}
    page = await client.get("/complete", params={"pending": pending}, headers=cookies)
    marker = "name='consent' value='"
    start = page.text.index(marker) + len(marker)
    app_origin = "{0.scheme}://{0.netloc}".format(urlparse(oauth._APP_BASE_URL))
    answer = await client.post(
        "/complete",
        data={
            "pending": pending,
            "consent": page.text[start : page.text.index("'", start)],
            "decision": "allow",
        },
        headers={**cookies, "origin": app_origin},
    )
    code = parse_qs(urlparse(answer.headers["location"]).query)["code"][0]
    token = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_when_metadata_ordinary_then_stored():
    async with _client() as client:
        response = await _register(client)

    assert response.status_code == 201
    stored = oauth._clients[response.json()["client_id"]]
    assert stored["client_name"] == "Test client"
    assert stored["redirect_uris"] == [REDIRECT]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_when_body_too_large_then_refused_and_nothing_stored():
    padding = "a" * MAX_REGISTRATION_BYTES
    async with _client() as client:
        response = await _register(client, redirect_uris=[f"{REDIRECT}?{padding}"])

    assert response.status_code == 413
    assert response.json()["error"] == "invalid_client_metadata"
    assert oauth._clients == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_when_large_body_sent_without_length_then_refused():
    """A chunked body declares no length, so the server counts as it reads."""

    async def chunks():
        yield b'{"client_name": "x", "redirect_uris": ["'
        for _ in range(MAX_REGISTRATION_BYTES // 1024 + 1):
            yield b"a" * 1024
        yield b'"]}'

    async with _client() as client:
        response = await client.post("/register", content=chunks())

    assert response.status_code == 413
    assert oauth._clients == {}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata, error",
    [
        ({"redirect_uris": REDIRECT}, "invalid_redirect_uri"),
        ({"redirect_uris": [REDIRECT, 7]}, "invalid_redirect_uri"),
        (
            {
                "redirect_uris": [
                    f"{REDIRECT}{n}" for n in range(oauth.MAX_REDIRECT_URIS + 1)
                ]
            },
            "invalid_redirect_uri",
        ),
        (
            {"redirect_uris": [REDIRECT + "x" * oauth.MAX_REDIRECT_URI_LENGTH]},
            "invalid_redirect_uri",
        ),
        (
            {"client_name": "n" * (oauth.MAX_CLIENT_NAME_LENGTH + 1)},
            "invalid_client_metadata",
        ),
        ({"client_name": ["not", "text"]}, "invalid_client_metadata"),
    ],
)
async def test_register_when_metadata_out_of_bounds_then_refused(metadata, error):
    async with _client() as client:
        response = await _register(client, **metadata)

    assert response.status_code == 400
    assert response.json()["error"] == error
    assert oauth._clients == {}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"not json", json.dumps(["a", "list"]).encode()])
async def test_register_when_body_not_a_json_object_then_refused(raw):
    async with _client() as client:
        response = await client.post(
            "/register", content=raw, headers={"content-type": "application/json"}
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    assert oauth._clients == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_when_store_full_then_oldest_never_used_client_dropped(
    monkeypatch,
):
    monkeypatch.setattr(oauth, "MAX_REGISTERED_CLIENTS", 3)
    async with _client() as client:
        used = (await _register(client)).json()["client_id"]
        await _get_token(client, used)
        unused_old = (await _register(client)).json()["client_id"]
        unused_new = (await _register(client)).json()["client_id"]

        newest = (await _register(client)).json()["client_id"]

    assert set(oauth._clients) == {used, unused_new, newest}
    assert unused_old not in oauth._clients


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_when_store_full_of_used_clients_then_oldest_dropped(
    monkeypatch,
):
    monkeypatch.setattr(oauth, "MAX_REGISTERED_CLIENTS", 2)
    async with _client() as client:
        first = (await _register(client)).json()["client_id"]
        await _get_token(client, first)
        second = (await _register(client)).json()["client_id"]
        await _get_token(client, second)

        third = (await _register(client)).json()["client_id"]

    assert set(oauth._clients) == {second, third}
