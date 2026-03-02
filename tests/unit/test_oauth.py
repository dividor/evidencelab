"""Unit tests for OAuth provider configuration (ui/backend/auth/oauth.py)."""

from unittest.mock import patch


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
