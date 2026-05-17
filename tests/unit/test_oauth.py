"""Unit tests for OAuth provider configuration (ui/backend/auth/oauth.py)."""

from unittest.mock import patch

import pytest
from fastapi_users.router.oauth import generate_state_token

from ui.backend.auth.users import AUTH_SECRET
from ui.backend.routes.auth import (
    _APP_BASE_URL,
    _is_safe_return_to,
    _resolve_post_login_redirect,
)


class TestOAuthConfiguration:
    """Tests for OAuth client initialization."""

    def test_google_client_created_when_configured(self):
        """Google OAuth client should be created when env vars are set."""
        env = {
            "OAUTH_GOOGLE_CLIENT_ID": "google-id",
            "OAUTH_GOOGLE_CLIENT_SECRET": "google-secret",  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.google_oauth_client is not None

    def test_google_client_none_when_not_configured(self):
        """Google OAuth client should be None when env vars are missing."""
        env = {
            "OAUTH_GOOGLE_CLIENT_ID": "",
            "OAUTH_GOOGLE_CLIENT_SECRET": "",  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.google_oauth_client is None

    def test_microsoft_client_created_when_configured(self):
        """Microsoft OAuth client should be created when env vars are set."""
        env = {
            "OAUTH_MICROSOFT_CLIENT_ID": "ms-id",
            "OAUTH_MICROSOFT_CLIENT_SECRET": "ms-secret",  # pragma: allowlist secret
            "OAUTH_MICROSOFT_TENANT_ID": "my-tenant",
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.microsoft_oauth_client is not None

    def test_microsoft_client_none_when_not_configured(self):
        """Microsoft OAuth client should be None when env vars are missing."""
        env = {
            "OAUTH_MICROSOFT_CLIENT_ID": "",
            "OAUTH_MICROSOFT_CLIENT_SECRET": "",  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.microsoft_oauth_client is None

    def test_microsoft_tenant_defaults_to_common(self):
        """Microsoft tenant should default to 'common' when not set."""
        env = {
            "OAUTH_MICROSOFT_CLIENT_ID": "ms-id",
            "OAUTH_MICROSOFT_CLIENT_SECRET": "ms-secret",  # pragma: allowlist secret
        }
        # Remove tenant env var
        with patch.dict("os.environ", env, clear=False):
            import os

            os.environ.pop("OAUTH_MICROSOFT_TENANT_ID", None)
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.MICROSOFT_TENANT_ID == "common"


class TestOAuthExplicitScopes:
    """Tests that OAuth clients use explicit, minimal scopes."""

    def test_google_client_has_explicit_scopes(self):
        """Google OAuth client should request openid, email, profile scopes."""
        env = {
            "OAUTH_GOOGLE_CLIENT_ID": "google-id",
            "OAUTH_GOOGLE_CLIENT_SECRET": "google-secret",  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.google_oauth_client is not None
            # Verify scopes are explicitly set
            scopes = mod.google_oauth_client.base_scopes
            assert "openid" in scopes
            assert "email" in scopes
            assert "profile" in scopes

    def test_microsoft_client_has_explicit_scopes(self):
        """Microsoft OAuth client should request OIDC + User.Read scopes."""
        env = {
            "OAUTH_MICROSOFT_CLIENT_ID": "ms-id",
            "OAUTH_MICROSOFT_CLIENT_SECRET": "ms-secret",  # pragma: allowlist secret
            "OAUTH_MICROSOFT_TENANT_ID": "my-tenant",
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            assert mod.microsoft_oauth_client is not None
            # Verify OIDC + Graph scopes are explicitly set
            scopes = mod.microsoft_oauth_client.base_scopes
            assert "openid" in scopes
            assert "email" in scopes
            assert "profile" in scopes
            # User.Read is required for Microsoft Graph /me endpoint
            assert "User.Read" in scopes

    def test_google_scopes_are_minimal(self):
        """Google OAuth client should not request excessive scopes."""
        env = {
            "OAUTH_GOOGLE_CLIENT_ID": "google-id",
            "OAUTH_GOOGLE_CLIENT_SECRET": "google-secret",  # pragma: allowlist secret
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            scopes = mod.google_oauth_client.base_scopes
            # Only these three scopes are needed for authentication
            assert len(scopes) == 3

    def test_microsoft_scopes_are_minimal(self):
        """Microsoft OAuth client should only request needed scopes."""
        env = {
            "OAUTH_MICROSOFT_CLIENT_ID": "ms-id",
            "OAUTH_MICROSOFT_CLIENT_SECRET": "ms-secret",  # pragma: allowlist secret
            "OAUTH_MICROSOFT_TENANT_ID": "my-tenant",
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.auth.oauth as mod

            importlib.reload(mod)
            scopes = mod.microsoft_oauth_client.base_scopes
            # 4 scopes: openid, email, profile, User.Read
            assert len(scopes) == 4


class TestIsSafeReturnTo:
    """Tests for the same-origin path validator used by the OAuth flow."""

    @pytest.mark.parametrize(
        "value",
        [
            "/",
            "/?q=foo",
            "/?q=impact+of+climate+change&rerank=false&sections=findings",
            "/admin?x=1",
            "/admin/users?page=2&sort=name",
            "/path/with/segments",
        ],
    )
    def test_accepts_same_origin_paths(self, value):
        assert _is_safe_return_to(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "//evil.com",
            "//evil.com/path",
            "/\\evil.com",
            "https://evil.com/",
            "http://evil.com",
            "javascript:alert(1)",
            "relative/path",
            "?q=foo",
        ],
    )
    def test_rejects_unsafe_values(self, value):
        assert _is_safe_return_to(value) is False

    def test_rejects_overly_long_paths(self):
        # 2049 chars — one over the cap
        too_long = "/" + ("a" * 2048)
        assert _is_safe_return_to(too_long) is False

    def test_accepts_path_at_length_limit(self):
        at_limit = "/" + ("a" * 2047)  # total length = 2048
        assert _is_safe_return_to(at_limit) is True


class TestResolvePostLoginRedirect:
    """Tests that the OAuth callback redirect respects the signed state JWT."""

    def test_returns_base_url_when_state_missing(self):
        assert _resolve_post_login_redirect(None) == _APP_BASE_URL
        assert _resolve_post_login_redirect("") == _APP_BASE_URL

    def test_returns_base_url_when_state_is_garbage(self):
        assert _resolve_post_login_redirect("not-a-jwt") == _APP_BASE_URL

    def test_returns_base_url_when_signature_invalid(self):
        # State signed with the wrong secret must not be trusted.
        wrong_secret = "x" * 32  # length matches AUTH_SECRET strength, value differs
        bad_state = generate_state_token({"return_to": "/?q=foo"}, wrong_secret)
        assert _resolve_post_login_redirect(bad_state) == _APP_BASE_URL

    def test_returns_base_url_when_return_to_missing(self):
        state = generate_state_token({"sub": "127.0.0.1"}, AUTH_SECRET)
        assert _resolve_post_login_redirect(state) == _APP_BASE_URL

    def test_returns_base_url_when_return_to_unsafe(self):
        # Even though state is signed, an unsafe return_to is still rejected
        # (defense in depth).
        state = generate_state_token({"return_to": "//evil.com"}, AUTH_SECRET)
        assert _resolve_post_login_redirect(state) == _APP_BASE_URL

    def test_appends_safe_return_to_to_base_url(self):
        return_to = "/?q=impact+of+climate+change&rerank=false"
        state = generate_state_token({"return_to": return_to}, AUTH_SECRET)
        expected = _APP_BASE_URL.rstrip("/") + return_to
        assert _resolve_post_login_redirect(state) == expected

    def test_strips_trailing_slash_from_base_url(self):
        with patch("ui.backend.routes.auth._APP_BASE_URL", "http://localhost:3000/"):
            state = generate_state_token({"return_to": "/?q=foo"}, AUTH_SECRET)
            assert _resolve_post_login_redirect(state) == "http://localhost:3000/?q=foo"
