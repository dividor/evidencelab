"""Shared checks used by the API-key dependency and the sign-in middleware."""

import secrets
import time

import jwt
import pytest

from ui.backend.auth.request_checks import (
    is_exempt_path,
    is_valid_session_token,
    path_is_under,
)

_SECRET = secrets.token_urlsafe(32)


def _token(secret=_SECRET, aud=("fastapi-users:auth",), expires_in=3600):
    return jwt.encode(
        {"sub": "u", "aud": list(aud), "exp": int(time.time()) + expires_in},
        secret,
        algorithm="HS256",
    )


@pytest.mark.parametrize(
    "path,prefix,expected",
    [
        ("/docs", "/docs", True),
        ("/docs/oauth2-redirect", "/docs", True),
        ("/docsearch", "/docs", False),
        ("/auth/login", "/auth/", True),
        ("/auth", "/auth/", True),
        ("/authx", "/auth/", False),
        ("/api-keys", "/api-keys", True),
        ("/api-keys/abc", "/api-keys", True),
        ("/api-keys-export", "/api-keys", False),
        ("/health", "/health", True),
        ("/healthz-admin", "/health", False),
    ],
)
def test_path_is_under_when_compared_then_matches_whole_segments(
    path, prefix, expected
):
    assert path_is_under(path, prefix) is expected


def test_is_exempt_path_when_any_prefix_matches_then_true():
    assert is_exempt_path("/users/me", ("/auth/", "/users/"))
    assert not is_exempt_path("/usersearch", ("/auth/", "/users/"))


def test_is_valid_session_token_when_signed_and_current_then_true():
    assert is_valid_session_token(_token(), _SECRET)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "junk",
        _token(secret=secrets.token_urlsafe(32)),
        _token(expires_in=-1),
        _token(aud=("some-other-audience",)),
    ],
    ids=["empty", "junk", "wrong-secret", "expired", "wrong-audience"],
)
def test_is_valid_session_token_when_not_a_valid_session_then_false(token):
    assert not is_valid_session_token(token, _SECRET)


def test_is_valid_session_token_when_no_secret_configured_then_false():
    assert not is_valid_session_token(_token(), "")
