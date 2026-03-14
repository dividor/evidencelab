"""Unit tests for security response headers middleware."""

from unittest.mock import patch

import httpx
import pytest

from ui.backend.auth.security_headers import SecurityHeadersMiddleware


def _make_app():
    """Create a minimal FastAPI app with SecurityHeadersMiddleware."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.post("/submit")
    async def submit_endpoint():
        return {"status": "created"}

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _client(app):
    """Create an httpx.AsyncClient for testing the ASGI app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestSecurityHeaders:
    """Verify all required security headers are present on responses."""

    @pytest.mark.asyncio
    async def test_x_content_type_options(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection_disabled(self):
        """Modern browsers should use CSP; legacy XSS filter is disabled."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.headers["X-XSS-Protection"] == "0"

    @pytest.mark.asyncio
    async def test_referrer_policy(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self):
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert "camera=()" in response.headers["Permissions-Policy"]
        assert "microphone=()" in response.headers["Permissions-Policy"]
        assert "geolocation=()" in response.headers["Permissions-Policy"]

    @pytest.mark.asyncio
    async def test_headers_on_post_response(self):
        """Security headers should appear on all responses, not just GET."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.post("/submit")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_headers_on_404_response(self):
        """Security headers should appear even on error responses."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/nonexistent")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


class TestHSTSHeader:
    """Test Strict-Transport-Security header (conditional on HTTPS config)."""

    @pytest.mark.asyncio
    async def test_hsts_present_when_cookie_secure_true(self):
        """HSTS should be set when AUTH_COOKIE_SECURE=true (production)."""
        with patch(
            "ui.backend.auth.security_headers._HSTS_VALUE",
            "max-age=31536000; includeSubDomains",
        ):
            app = _make_app()
            async with _client(app) as client:
                response = await client.get("/test")
            assert "Strict-Transport-Security" in response.headers
            assert "max-age=" in response.headers["Strict-Transport-Security"]

    @pytest.mark.asyncio
    async def test_hsts_absent_when_cookie_secure_false(self):
        """HSTS should NOT be set when running in development (HTTP)."""
        with patch("ui.backend.auth.security_headers._HSTS_VALUE", ""):
            app = _make_app()
            async with _client(app) as client:
                response = await client.get("/test")
            assert "Strict-Transport-Security" not in response.headers
            # Other headers should still be present
            assert response.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_hsts_includes_preload_directive(self):
        """HSTS should include preload directive for HSTS preload list."""
        with patch(
            "ui.backend.auth.security_headers._HSTS_VALUE",
            "max-age=31536000; includeSubDomains; preload",
        ):
            app = _make_app()
            async with _client(app) as client:
                response = await client.get("/test")
            hsts = response.headers["Strict-Transport-Security"]
            assert "preload" in hsts
            assert "includeSubDomains" in hsts


class TestCSPHeader:
    """Test Content-Security-Policy header."""

    @pytest.mark.asyncio
    async def test_csp_header_present(self):
        """CSP header should be present on all responses."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        assert "Content-Security-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_csp_default_policy(self):
        """Default CSP policy should restrict to self with GA allowlisted."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_csp_script_src_has_no_unsafe_inline(self):
        """script-src should NOT contain 'unsafe-inline' (ASVS V14.4.3)."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        # Extract script-src directive
        for directive in csp.split(";"):
            if "script-src" in directive:
                assert "'unsafe-inline'" not in directive

    @pytest.mark.asyncio
    async def test_csp_script_src_has_hash(self):
        """script-src should contain a sha256 hash for the inline GA script."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "'sha256-" in csp

    @pytest.mark.asyncio
    async def test_csp_script_src_allows_google_analytics(self):
        """script-src should allow Google Tag Manager and Analytics domains."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "https://www.googletagmanager.com" in csp
        assert "https://www.google-analytics.com" in csp

    @pytest.mark.asyncio
    async def test_csp_connect_src_allows_google_analytics(self):
        """connect-src should allow GA domains for analytics data."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        for directive in csp.split(";"):
            if "connect-src" in directive:
                assert "https://www.google-analytics.com" in directive
                break
        else:
            pytest.fail("connect-src directive not found in CSP")

    @pytest.mark.asyncio
    async def test_csp_style_src_allows_unsafe_inline(self):
        """style-src must keep 'unsafe-inline' — React requires it."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        for directive in csp.split(";"):
            if "style-src" in directive:
                assert "'unsafe-inline'" in directive
                break
        else:
            pytest.fail("style-src directive not found in CSP")

    @pytest.mark.asyncio
    async def test_csp_custom_policy_from_env(self):
        """CSP policy should be configurable via CSP_POLICY env var."""
        custom_csp = "default-src 'self'; script-src 'self' https://cdn.example.com"
        with patch("ui.backend.auth.security_headers._CSP_POLICY", custom_csp):
            app = _make_app()
            async with _client(app) as client:
                response = await client.get("/test")
            assert response.headers["Content-Security-Policy"] == custom_csp

    @pytest.mark.asyncio
    async def test_csp_on_error_responses(self):
        """CSP header should appear even on error responses."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.get("/nonexistent")
        assert "Content-Security-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_csp_on_post_responses(self):
        """CSP header should appear on POST responses."""
        app = _make_app()
        async with _client(app) as client:
            response = await client.post("/submit")
        assert "Content-Security-Policy" in response.headers


class TestCacheControlHeaders:
    """Test Cache-Control: no-store on sensitive endpoints (ASVS V8.1.4)."""

    @staticmethod
    def _make_app_with_sensitive_routes():
        """Create an app with sensitive path endpoints."""
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/test")
        async def public_endpoint():
            return {"status": "ok"}

        @app.get("/auth/login")
        async def auth_endpoint():
            return {"status": "ok"}

        @app.get("/users/me")
        async def users_endpoint():
            return {"status": "ok"}

        @app.get("/groups/list")
        async def groups_endpoint():
            return {"status": "ok"}

        @app.get("/ratings/summary")
        async def ratings_endpoint():
            return {"status": "ok"}

        @app.get("/activity/recent")
        async def activity_endpoint():
            return {"status": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)
        return app

    @pytest.mark.asyncio
    async def test_cache_control_on_auth_endpoint(self):
        """Auth endpoints should have Cache-Control: no-store."""
        app = self._make_app_with_sensitive_routes()
        async with _client(app) as client:
            response = await client.get("/auth/login")
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.headers.get("Pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_cache_control_on_users_endpoint(self):
        """User endpoints should have Cache-Control: no-store."""
        app = self._make_app_with_sensitive_routes()
        async with _client(app) as client:
            response = await client.get("/users/me")
        assert response.headers.get("Cache-Control") == "no-store"

    @pytest.mark.asyncio
    async def test_cache_control_on_groups_endpoint(self):
        """Group endpoints should have Cache-Control: no-store."""
        app = self._make_app_with_sensitive_routes()
        async with _client(app) as client:
            response = await client.get("/groups/list")
        assert response.headers.get("Cache-Control") == "no-store"

    @pytest.mark.asyncio
    async def test_no_cache_control_on_public_endpoint(self):
        """Public endpoints should NOT have Cache-Control: no-store."""
        app = self._make_app_with_sensitive_routes()
        async with _client(app) as client:
            response = await client.get("/test")
        assert response.headers.get("Cache-Control") != "no-store"
