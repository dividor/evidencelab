"""Unit tests for the OAuth-only cookie logout route.

In OAuth-only deployments (``DISABLE_EMAIL_LOGIN=true``) the email/password
auth router — which normally carries ``/cookie-login/logout`` — is not mounted,
so a standalone logout is registered instead. These tests verify that route
exists, clears the auth cookie, and still requires a valid session. The route
is registered at import time from the env var, so the module is reloaded per
mode.
"""

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

COOKIE_NAME = "evidencelab_auth"
LOGOUT_PATH = "/auth/cookie-login/logout"


@pytest.fixture
def oauth_only_auth_routes(monkeypatch):
    """Reload the auth routes module in OAuth-only mode, then restore it.

    Args:
        monkeypatch: pytest fixture used to set ``DISABLE_EMAIL_LOGIN``.

    Yields:
        module: The reloaded ``ui.backend.routes.auth`` module.
    """
    monkeypatch.setenv("DISABLE_EMAIL_LOGIN", "true")
    from ui.backend.routes import auth as auth_routes

    yield importlib.reload(auth_routes)

    # Restore the module to its env-default state so other tests are unaffected.
    monkeypatch.undo()
    importlib.reload(auth_routes)


def _build_app(auth_routes, *, authenticated: bool) -> FastAPI:
    """Mount the auth router, optionally overriding auth to authenticated.

    Args:
        auth_routes: The (reloaded) auth routes module.
        authenticated: When True, treat requests as an authenticated user.

    Returns:
        FastAPI: The configured application.
    """
    from ui.backend.auth.users import current_active_user

    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    if authenticated:
        app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(
            id="user-1"
        )
    return app


@pytest.mark.unit
def test_cookie_logout_route_registered_in_oauth_only_mode(oauth_only_auth_routes):
    """The standalone logout route exists when email login is disabled."""
    paths = {route.path for route in oauth_only_auth_routes.router.routes}
    assert "/cookie-login/logout" in paths


@pytest.mark.unit
def test_cookie_logout_when_authenticated_clears_cookie(oauth_only_auth_routes):
    """An authenticated logout returns 204 and expires the auth cookie."""
    client = TestClient(_build_app(oauth_only_auth_routes, authenticated=True))

    resp = client.post(LOGOUT_PATH)

    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert f"{COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie


@pytest.mark.unit
def test_cookie_logout_requires_authentication(oauth_only_auth_routes):
    """Logout without a valid session is rejected (nothing to clear)."""
    client = TestClient(_build_app(oauth_only_auth_routes, authenticated=False))

    resp = client.post(LOGOUT_PATH)

    assert resp.status_code == 401
