"""Password recovery is offered only where people sign in with a password.

With DISABLE_EMAIL_LOGIN set, nobody signs in with a password, so a reset one
could never be used: the forgot-password and reset-password routes are not
mounted. Signing out and email verification are unaffected. Routes are
registered at import time from the env var, so the module is reloaded per mode.
"""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

RECOVERY_PATHS = {"/forgot-password", "/reset-password"}


@pytest.fixture
def auth_routes_in_mode(monkeypatch):
    """Reload the auth routes module in a login mode; restore it afterwards."""

    def reload(*, disable_email_login: bool):
        monkeypatch.setenv(
            "DISABLE_EMAIL_LOGIN", "true" if disable_email_login else "false"
        )
        from ui.backend.routes import auth as auth_routes

        return importlib.reload(auth_routes)

    yield reload
    monkeypatch.undo()
    from ui.backend.routes import auth as auth_routes

    importlib.reload(auth_routes)


def _paths(auth_routes) -> set:
    return {route.path for route in auth_routes.router.routes}


def _client(auth_routes) -> TestClient:
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    return TestClient(app)


@pytest.mark.unit
def test_recovery_routes_when_email_login_off_then_not_mounted(auth_routes_in_mode):
    auth_routes = auth_routes_in_mode(disable_email_login=True)

    assert not RECOVERY_PATHS & _paths(auth_routes)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path, body",
    [
        ("/auth/forgot-password", {"email": "person@example.org"}),
        ("/auth/reset-password", {"token": "any"}),
    ],
)
def test_recovery_request_when_email_login_off_then_not_found(
    auth_routes_in_mode, path, body
):
    client = _client(auth_routes_in_mode(disable_email_login=True))

    assert client.post(path, json=body).status_code == 404


@pytest.mark.unit
def test_recovery_routes_when_email_login_on_then_mounted(auth_routes_in_mode):
    auth_routes = auth_routes_in_mode(disable_email_login=False)

    assert RECOVERY_PATHS <= _paths(auth_routes)


@pytest.mark.unit
@pytest.mark.parametrize("disable_email_login", [True, False])
def test_sign_out_and_verify_when_either_mode_then_still_mounted(
    auth_routes_in_mode, disable_email_login
):
    auth_routes = auth_routes_in_mode(disable_email_login=disable_email_login)

    paths = _paths(auth_routes)
    assert "/cookie-login/logout" in paths
    assert {"/request-verify-token", "/verify"} <= paths
    response = _client(auth_routes).post("/auth/cookie-login/logout")
    assert response.status_code == 204
