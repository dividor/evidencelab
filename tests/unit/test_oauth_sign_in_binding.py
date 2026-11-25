"""Tests that a Google/Microsoft sign-in is bound to the browser that started it.

/authorize sets a PKCE verifier cookie and puts its S256 challenge in the
signed state; /callback must refuse a state it did not issue to this browser,
and must send the verifier with the code.
"""

import base64
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_users.jwt import generate_jwt
from fastapi_users.router.oauth import STATE_TOKEN_AUDIENCE, generate_state_token
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.microsoft import MicrosoftGraphOAuth2

from ui.backend.auth.users import AUTH_SECRET, cookie_backend, get_user_manager
from ui.backend.routes import auth as auth_routes
from ui.backend.routes.auth import (
    _OAUTH_FLOW_COOKIE,
    _OAUTH_FLOW_SECONDS,
    _make_oauth_router,
    _pkce_challenge,
)

pytestmark = pytest.mark.unit

CALLBACK_PATH = "/auth/microsoft/callback"
CALLBACK_URL = f"{auth_routes._OAUTH_CALLBACK_BASE}{CALLBACK_PATH}"
INVALID = {"detail": "OAUTH_INVALID_STATE"}


class FakeProvider:
    """Stands in for an httpx-oauth client; records what the router asks of it."""

    name = "microsoft"

    def __init__(self):
        self.authorize_calls = []
        self.token_calls = []

    async def get_authorization_url(
        self, redirect_uri, state=None, scope=None, extras_params=None
    ):
        self.authorize_calls.append((redirect_uri, state, scope, extras_params))
        return f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?state={state}"

    async def get_access_token(self, code, redirect_uri, code_verifier=None):
        self.token_calls.append((code, redirect_uri, code_verifier))
        return {"access_token": "provider-token", "expires_at": None}

    async def get_id_email(self, token):
        return "account-1", "person@example.org"


class FakeUserManager:
    async def oauth_callback(self, *args, **kwargs):
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001", is_active=True
        )


class FakeStrategy:
    async def write_token(self, user):
        return "session-token"


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def client(provider):
    app = FastAPI()
    app.include_router(
        _make_oauth_router(provider, "microsoft"), prefix="/auth/microsoft"
    )
    app.dependency_overrides[get_user_manager] = lambda: FakeUserManager()
    app.dependency_overrides[cookie_backend.get_strategy] = lambda: FakeStrategy()
    # https, so the browser-side cookie jar sends the Secure flow cookie back.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def _start(client):
    """Start a sign-in; return (state, verifier) as the browser holds them."""
    response = client.get(
        "/auth/microsoft/authorize", params={"return_to": "/?q=meals"}
    )
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return state, client.cookies.get(_OAUTH_FLOW_COOKIE)


def _finish(client, state, code="provider-code"):
    params = {"code": code}
    if state is not None:
        params["state"] = state
    return client.get(CALLBACK_PATH, params=params, follow_redirects=False)


# RFC 7636 Appendix B: the 32 random octets behind the example code verifier,
# and the octets of the SHA-256 of that verifier, which its S256 challenge
# encodes.
RFC7636_RANDOM_OCTETS = (
    [116, 24, 223, 180, 151, 153, 224, 37]
    + [79, 250, 96, 125, 216, 173, 187, 186]
    + [22, 212, 37, 77, 105, 214, 191, 240]
    + [91, 88, 5, 88, 83, 132, 141, 121]
)
RFC7636_HASH_OCTETS = (
    [19, 211, 30, 150, 26, 26, 216, 236]
    + [47, 22, 177, 12, 76, 152, 46, 8]
    + [118, 168, 120, 173, 109, 241, 68, 86]
    + [110, 225, 137, 74, 203, 112, 249, 195]
)


def _base64url(octets: list[int]) -> str:
    return base64.urlsafe_b64encode(bytes(octets)).rstrip(b"=").decode("ascii")


class TestPkceChallenge:
    def test_pkce_challenge_when_rfc7636_example_then_matches_appendix_b(self):
        verifier = _base64url(RFC7636_RANDOM_OCTETS)

        assert _pkce_challenge(verifier) == _base64url(RFC7636_HASH_OCTETS)


class TestAuthorize:
    def test_authorize_when_called_then_sets_a_locked_down_flow_cookie(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(auth_routes, "_AUTH_COOKIE_SECURE", True)
        response = client.get("/auth/microsoft/authorize")

        set_cookie = response.headers["set-cookie"]
        assert set_cookie.startswith(f"{_OAUTH_FLOW_COOKIE}=")
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert f"Path={CALLBACK_PATH}" in set_cookie
        assert f"Max-Age={_OAUTH_FLOW_SECONDS}" in set_cookie

    def test_authorize_when_secure_cookies_off_then_cookie_not_secure(
        self, client, monkeypatch
    ):
        # AUTH_COOKIE_SECURE=false is for plain-http local development only.
        monkeypatch.setattr(auth_routes, "_AUTH_COOKIE_SECURE", False)
        response = client.get("/auth/microsoft/authorize")

        assert "Secure" not in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]

    def test_authorize_when_called_then_state_carries_the_cookie_challenge(
        self, client, provider
    ):
        state, verifier = _start(client)

        redirect_uri, sent_state, scope, extras = provider.authorize_calls[0]
        assert redirect_uri == CALLBACK_URL
        assert sent_state == state
        assert scope is None
        assert extras == {
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        assert 43 <= len(verifier) <= 128

    def test_authorize_when_scopes_asked_for_then_ignores_them(self, client, provider):
        client.get("/auth/microsoft/authorize", params={"scopes": "Mail.Read"})

        assert provider.authorize_calls[0][2] is None

    def test_authorize_when_called_twice_then_uses_a_new_verifier(self, client):
        _, first = _start(client)
        _, second = _start(client)

        assert first != second

    def test_authorize_when_account_choice_asked_for_then_passes_it_on(
        self, client, provider
    ):
        response = client.get(
            "/auth/microsoft/authorize", params={"prompt": "select_account"}
        )

        assert response.status_code == 200
        extras = provider.authorize_calls[0][3]
        assert extras["prompt"] == "select_account"
        assert extras["code_challenge_method"] == "S256"

    @pytest.mark.parametrize("prompt", ["none", "login", "consent", ""])
    def test_authorize_when_other_prompt_asked_for_then_refuses(
        self, client, provider, prompt
    ):
        response = client.get("/auth/microsoft/authorize", params={"prompt": prompt})

        assert response.status_code == 422
        assert provider.authorize_calls == []
        assert _OAUTH_FLOW_COOKIE not in response.cookies


class TestCallback:
    def test_callback_when_same_browser_then_signs_in_with_the_verifier(
        self, client, provider
    ):
        state, verifier = _start(client)

        response = _finish(client, state)

        assert response.status_code == 302
        assert response.headers["location"].endswith("/?q=meals")
        assert provider.token_calls == [("provider-code", CALLBACK_URL, verifier)]
        cookies = response.headers.get_list("set-cookie")
        assert any(c.startswith("evidencelab_auth=session-token") for c in cookies)
        cleared = [c for c in cookies if c.startswith(f"{_OAUTH_FLOW_COOKIE}=")]
        assert cleared and "Max-Age=0" in cleared[0]
        assert f"Path={CALLBACK_PATH}" in cleared[0]

    def test_callback_when_no_flow_cookie_then_refuses(self, client, provider):
        state, _ = _start(client)
        client.cookies.clear()

        response = _finish(client, state)

        assert response.status_code == 400
        assert response.json() == INVALID
        assert provider.token_calls == []

    def test_callback_when_state_from_another_browser_then_refuses(
        self, client, provider
    ):
        other_state, _ = _start(client)
        client.cookies.clear()
        _start(client)

        response = _finish(client, other_state)

        assert response.status_code == 400
        assert response.json() == INVALID
        assert provider.token_calls == []

    def test_callback_when_no_state_then_refuses(self, client, provider):
        _start(client)

        response = _finish(client, None)

        assert response.status_code == 400
        assert response.json() == INVALID
        assert provider.token_calls == []

    def test_callback_when_state_not_ours_then_refuses(self, client, provider):
        _, verifier = _start(client)
        forged = generate_state_token(
            {"challenge": _pkce_challenge(verifier)},
            "another-secret-of-at-least-32-chars!!",
        )

        response = _finish(client, forged)

        assert response.status_code == 400
        assert provider.token_calls == []

    def test_callback_when_state_garbage_then_refuses(self, client, provider):
        _start(client)

        response = _finish(client, "not-a-token")

        assert response.status_code == 400
        assert provider.token_calls == []

    def test_callback_when_state_expired_then_refuses(self, client, provider):
        _, verifier = _start(client)
        expired = generate_state_token(
            {"challenge": _pkce_challenge(verifier)}, AUTH_SECRET, lifetime_seconds=-1
        )

        response = _finish(client, expired)

        assert response.status_code == 400
        assert provider.token_calls == []

    def test_callback_when_token_for_another_audience_then_refuses(
        self, client, provider
    ):
        _, verifier = _start(client)
        session_like = generate_jwt(
            {"challenge": _pkce_challenge(verifier), "aud": "fastapi-users:auth"},
            AUTH_SECRET,
            600,
        )

        response = _finish(client, session_like)

        assert response.status_code == 400
        assert provider.token_calls == []

    def test_callback_when_state_has_no_challenge_then_refuses(self, client, provider):
        _start(client)
        old_style = generate_state_token({"sub": "203.0.113.9"}, AUTH_SECRET)

        response = _finish(client, old_style)

        assert response.status_code == 400
        assert provider.token_calls == []


REAL_PROVIDERS = [
    (
        MicrosoftGraphOAuth2(
            "client-id",
            "client-secret",
            tenant="common",
            scopes=["openid", "email", "profile", "User.Read"],
        ),
        "login.microsoftonline.com",
    ),
    (
        GoogleOAuth2(
            "client-id",
            "client-secret",
            scopes=["openid", "email", "profile"],
        ),
        "accounts.google.com",
    ),
]


def _real_authorize(provider_client, params=None):
    """Ask a router on a real httpx-oauth client for a sign-in address."""
    app = FastAPI()
    app.include_router(
        _make_oauth_router(provider_client, "microsoft"), prefix="/auth/microsoft"
    )
    with TestClient(app, base_url="https://testserver") as test_client:
        response = test_client.get("/auth/microsoft/authorize", params=params)
        verifier = test_client.cookies.get(_OAUTH_FLOW_COOKIE)
    return urlparse(response.json()["authorization_url"]), verifier


class TestRealProviderAddresses:
    """The real httpx-oauth clients put the PKCE challenge in the sign-in address."""

    @pytest.mark.parametrize("provider_client, host", REAL_PROVIDERS)
    def test_authorize_when_account_choice_asked_for_then_address_asks_for_it(
        self, provider_client, host
    ):
        url, _ = _real_authorize(provider_client, {"prompt": "select_account"})

        assert url.hostname == host
        assert parse_qs(url.query)["prompt"] == ["select_account"]

    @pytest.mark.parametrize("provider_client, host", REAL_PROVIDERS)
    def test_authorize_when_nothing_asked_for_then_address_has_no_prompt(
        self, provider_client, host
    ):
        url, _ = _real_authorize(provider_client)

        assert url.hostname == host
        assert "prompt" not in parse_qs(url.query)

    @pytest.mark.parametrize("provider_client, host", REAL_PROVIDERS)
    def test_authorize_when_real_client_then_address_has_s256_challenge(
        self, provider_client, host
    ):
        url, verifier = _real_authorize(provider_client)
        query = parse_qs(url.query)
        assert url.scheme == "https" and url.hostname == host
        assert query["code_challenge"] == [_pkce_challenge(verifier)]
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [CALLBACK_URL]
        state = query["state"][0]
        from fastapi_users.jwt import decode_jwt

        state_data = decode_jwt(state, AUTH_SECRET, [STATE_TOKEN_AUDIENCE])
        assert state_data["challenge"] == _pkce_challenge(verifier)
        assert "sub" not in state_data


class _ProviderRefusal(Exception):
    """Shaped like httpx-oauth's GetAccessTokenError: it carries the response."""

    def __init__(self, response):
        super().__init__("token request failed")
        self.response = response


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class TestFailureLogging:
    """Why a sign-in failed goes to the server log, never to the browser."""

    def test_exchange_when_provider_refuses_then_logs_its_reason(
        self, client, provider, caplog
    ):
        refusal = _Response(
            401,
            {
                "error": "invalid_client",
                "error_codes": [7000222],
                "error_description": (
                    "AADSTS7000222: The client secret keys are expired.\nTrace ID: x"
                ),
            },
        )

        async def refuse(*args, **kwargs):
            raise _ProviderRefusal(refusal)

        provider.get_access_token = refuse
        state, _ = _start(client)
        with caplog.at_level("WARNING", logger="ui.backend.routes.auth"):
            response = _finish(client, state)

        assert response.status_code == 400
        assert response.json() == {"detail": "OAUTH_EXCHANGE_ERROR"}
        assert "AADSTS7000222" not in response.text
        logged = caplog.text
        assert "OAuth microsoft token exchange failed" in logged
        assert "HTTP 401 error=invalid_client codes=[7000222]" in logged
        assert "AADSTS7000222: The client secret keys are expired." in logged
        assert "Trace ID" not in logged

    def test_provider_error_when_body_not_json_then_says_so(self):
        exc = _ProviderRefusal(_Response(502, None))
        assert auth_routes._provider_error(exc) == "HTTP 502, body not JSON"

    def test_provider_error_when_no_response_then_names_the_exception(self):
        assert auth_routes._provider_error(TimeoutError("timed out")) == (
            "TimeoutError: timed out"
        )

    def test_user_step_when_it_fails_then_logs_the_traceback(
        self, client, caplog, monkeypatch
    ):
        async def fail(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(FakeUserManager, "oauth_callback", fail)
        state, _ = _start(client)
        with caplog.at_level("ERROR", logger="ui.backend.routes.auth"):
            response = _finish(client, state)

        assert response.status_code == 400
        assert "database unavailable" not in response.text
        assert "could not create or link the user" in caplog.text
        assert "RuntimeError: database unavailable" in caplog.text
