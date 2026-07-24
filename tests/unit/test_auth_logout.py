"""Unit tests for the unconditional cookie logout route.

Signing out must never depend on being signed in: a user whose session cookie
is stale (expired mid-session, network/VPN transition) still needs the cookie
cleared, otherwise they are stuck with a broken session they can neither use
nor discard. The logout route is therefore registered before the built-in
fastapi-users auth routers (first-registered route wins) and requires no
authentication, in both email-login and OAuth-only deployments. Routes are
registered at import time from the env var, so the module is reloaded per mode.
"""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

COOKIE_NAME = "evidencelab_auth"
LOGOUT_PATH = "/auth/cookie-login/logout"


def _reload_auth_routes(monkeypatch, *, disable_email_login: bool):
    """Reload the auth routes module under the given login mode.

    Args:
        monkeypatch: pytest fixture used to set ``DISABLE_EMAIL_LOGIN``.
        disable_email_login: When True, reload in OAuth-only mode.

    Returns:
        module: The reloaded ``ui.backend.routes.auth`` module.
    """
    monkeypatch.setenv(
        "DISABLE_EMAIL_LOGIN", "true" if disable_email_login else "false"
    )
    from ui.backend.routes import auth as auth_routes

    return importlib.reload(auth_routes)


@pytest.fixture
def oauth_only_auth_routes(monkeypatch):
    """Auth routes module reloaded in OAuth-only mode, restored afterwards."""
    yield _reload_auth_routes(monkeypatch, disable_email_login=True)
    monkeypatch.undo()
    from ui.backend.routes import auth as auth_routes

    importlib.reload(auth_routes)


@pytest.fixture
def email_login_auth_routes(monkeypatch):
    """Auth routes module reloaded with email login enabled, restored after."""
    yield _reload_auth_routes(monkeypatch, disable_email_login=False)
    monkeypatch.undo()
    from ui.backend.routes import auth as auth_routes

    importlib.reload(auth_routes)


def _build_app(auth_routes) -> FastAPI:
    """Mount the auth router on a bare app (no auth overrides).

    Args:
        auth_routes: The (reloaded) auth routes module.

    Returns:
        FastAPI: The configured application.
    """
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    return app


def _assert_logout_clears_cookie(resp) -> None:
    """Assert a logout response expires the auth cookie."""
    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert f"{COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie


@pytest.mark.unit
def test_cookie_logout_route_registered_in_oauth_only_mode(oauth_only_auth_routes):
    """The logout route exists when email login is disabled."""
    paths = {route.path for route in oauth_only_auth_routes.router.routes}
    assert "/cookie-login/logout" in paths


@pytest.mark.unit
def test_cookie_logout_without_session_clears_cookie_oauth_only(
    oauth_only_auth_routes,
):
    """Logout with no session cookie still succeeds and expires the cookie.

    A user with a stale or missing session must always be able to sign out —
    logout must not require being logged in.
    """
    client = TestClient(_build_app(oauth_only_auth_routes))

    resp = client.post(LOGOUT_PATH)

    _assert_logout_clears_cookie(resp)


@pytest.mark.unit
def test_cookie_logout_without_session_clears_cookie_email_mode(
    email_login_auth_routes,
):
    """With email login enabled, the unconditional logout shadows the built-in.

    fastapi-users' own /cookie-login/logout returns 401 without a valid
    session; the unconditional route is registered first so it wins.
    """
    client = TestClient(_build_app(email_login_auth_routes))

    resp = client.post(LOGOUT_PATH)

    _assert_logout_clears_cookie(resp)


@pytest.mark.unit
def test_cookie_logout_with_stale_cookie_clears_cookie(oauth_only_auth_routes):
    """Logout with an invalid (expired/garbage) cookie still clears it."""
    client = TestClient(_build_app(oauth_only_auth_routes))
    client.cookies.set(COOKIE_NAME, "not-a-valid-jwt")

    resp = client.post(LOGOUT_PATH)

    _assert_logout_clears_cookie(resp)
