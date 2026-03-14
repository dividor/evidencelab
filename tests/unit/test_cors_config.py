"""Unit tests for CORS header configuration in main.py."""

from unittest.mock import patch


class TestCORSHeadersConfig:
    """Tests for CORS_ALLOWED_HEADERS env-based configuration."""

    def test_cors_headers_from_env(self):
        """CORS_ALLOWED_HEADERS env var should be parsed into a list."""
        env = {"CORS_ALLOWED_HEADERS": "Content-Type,Authorization,X-Custom"}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert "Content-Type" in mod.CORS_HEADERS
            assert "Authorization" in mod.CORS_HEADERS
            assert "X-Custom" in mod.CORS_HEADERS
            assert len(mod.CORS_HEADERS) == 3

    def test_cors_headers_strips_whitespace(self):
        """Whitespace around header names should be trimmed."""
        env = {"CORS_ALLOWED_HEADERS": " Content-Type , Authorization "}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert "Content-Type" in mod.CORS_HEADERS
            assert "Authorization" in mod.CORS_HEADERS

    def test_cors_headers_defaults_when_empty(self):
        """When CORS_ALLOWED_HEADERS is empty, a secure default whitelist is used."""
        env = {"CORS_ALLOWED_HEADERS": ""}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            # Should have the default headers
            assert "Content-Type" in mod.CORS_HEADERS
            assert "Authorization" in mod.CORS_HEADERS
            assert "X-API-Key" in mod.CORS_HEADERS
            assert "X-CSRF-Token" in mod.CORS_HEADERS
            assert "Accept" in mod.CORS_HEADERS
            assert "Accept-Language" in mod.CORS_HEADERS

    def test_cors_headers_defaults_when_unset(self):
        """When CORS_ALLOWED_HEADERS is not in env, defaults are used."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("CORS_ALLOWED_HEADERS", None)
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            # Wildcard "*" should NOT be in the defaults
            assert "*" not in mod.CORS_HEADERS
            # Default whitelist should be populated
            assert len(mod.CORS_HEADERS) >= 4

    def test_cors_headers_no_wildcard_in_defaults(self):
        """Default CORS headers should never include wildcard '*'."""
        env = {"CORS_ALLOWED_HEADERS": ""}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert "*" not in mod.CORS_HEADERS

    def test_cors_headers_ignores_empty_entries(self):
        """Trailing commas / empty entries should be ignored."""
        env = {"CORS_ALLOWED_HEADERS": "Content-Type,,Authorization,"}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert len(mod.CORS_HEADERS) == 2
            assert "Content-Type" in mod.CORS_HEADERS
            assert "Authorization" in mod.CORS_HEADERS


class TestCORSOriginsConfig:
    """Tests for CORS_ALLOWED_ORIGINS env-based configuration."""

    def test_cors_origins_from_env(self):
        """CORS_ALLOWED_ORIGINS env var should be parsed into a list."""
        env = {
            "CORS_ALLOWED_ORIGINS": "https://app.example.com,https://api.example.com"
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert "https://app.example.com" in mod.CORS_ORIGINS
            assert "https://api.example.com" in mod.CORS_ORIGINS

    def test_cors_origins_defaults_to_localhost(self):
        """When CORS_ALLOWED_ORIGINS is empty, localhost dev origins are used."""
        env = {"CORS_ALLOWED_ORIGINS": ""}
        with patch.dict("os.environ", env, clear=False):
            import importlib

            import ui.backend.main as mod

            importlib.reload(mod)
            assert "http://localhost:3000" in mod.CORS_ORIGINS
