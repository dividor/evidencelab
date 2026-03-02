"""Unit tests for the authentication rate limiting module."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from ui.backend.auth.rate_limit import (
    AUTH_RATE_LIMIT_MAX,
    AUTH_RATE_LIMIT_WINDOW,
    _gc_expired_entries,
    _request_log,
    check_auth_rate_limit,
    current_request_ip,
)


def _make_request(ip="127.0.0.1"):
    """Create a mock Request object with given IP."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = ip
    return request


class TestCheckAuthRateLimit:
    """Tests for the check_auth_rate_limit dependency."""

    def setup_method(self):
        """Clear the request log before each test."""
        _request_log.clear()

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self):
        """Requests below the threshold should pass."""
        request = _make_request("10.0.0.1")
        # Should not raise for a few requests
        for _ in range(3):
            await check_auth_rate_limit(request)

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self):
        """Requests exceeding the threshold should get 429."""
        request = _make_request("10.0.0.2")
        # Fill up to the limit
        for _ in range(AUTH_RATE_LIMIT_MAX):
            await check_auth_rate_limit(request)
        # Next request should be blocked
        with pytest.raises(HTTPException) as exc_info:
            await check_auth_rate_limit(request)
        assert exc_info.value.status_code == 429
        assert "Too many" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_different_ips_have_separate_limits(self):
        """Each IP address has its own rate limit counter."""
        request_a = _make_request("10.0.0.3")
        request_b = _make_request("10.0.0.4")
        # Fill up limit for IP A
        for _ in range(AUTH_RATE_LIMIT_MAX):
            await check_auth_rate_limit(request_a)
        # IP B should still work
        await check_auth_rate_limit(request_b)

    @pytest.mark.asyncio
    async def test_sets_context_var(self):
        """The dependency should set current_request_ip context var."""
        request = _make_request("192.168.1.100")
        await check_auth_rate_limit(request)
        assert current_request_ip.get() == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_handles_missing_client(self):
        """If request.client is None, use 'unknown' as the IP."""
        request = MagicMock()
        request.client = None
        await check_auth_rate_limit(request)
        assert current_request_ip.get() == "unknown"

    @pytest.mark.asyncio
    async def test_expired_entries_pruned(self):
        """Entries older than the window should be pruned on each call."""
        ip = "10.0.0.5"
        # Manually insert old timestamps
        old_time = time.monotonic() - AUTH_RATE_LIMIT_WINDOW - 10
        _request_log[ip] = [old_time] * AUTH_RATE_LIMIT_MAX

        request = _make_request(ip)
        # Should pass because old entries should be pruned
        await check_auth_rate_limit(request)
        # The old entries should be gone, only the new one remains
        assert len(_request_log[ip]) == 1


class TestGarbageCollection:
    """Tests for _gc_expired_entries."""

    def setup_method(self):
        _request_log.clear()

    def test_removes_fully_expired_ips(self):
        """IPs with only expired timestamps should be removed."""
        old_time = time.monotonic() - AUTH_RATE_LIMIT_WINDOW - 10
        _request_log["expired-ip"] = [old_time, old_time - 1]
        _request_log["active-ip"] = [time.monotonic()]

        _gc_expired_entries()

        assert "expired-ip" not in _request_log
        assert "active-ip" in _request_log

    def test_keeps_ips_with_recent_entries(self):
        """IPs with at least one recent timestamp should be kept."""
        now = time.monotonic()
        _request_log["mixed-ip"] = [now - AUTH_RATE_LIMIT_WINDOW - 5, now]

        _gc_expired_entries()

        assert "mixed-ip" in _request_log

    def test_handles_empty_log(self):
        """GC on an empty log should not error."""
        _gc_expired_entries()
        assert len(_request_log) == 0


class TestRateLimitConfiguration:
    """Tests for rate limit environment configuration."""

    def test_default_max_is_10(self):
        assert AUTH_RATE_LIMIT_MAX == 10

    def test_default_window_is_60(self):
        assert AUTH_RATE_LIMIT_WINDOW == 60

    def test_custom_values_from_env(self):
        """Custom values should be read from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "AUTH_RATE_LIMIT_MAX": "20",
                "AUTH_RATE_LIMIT_WINDOW": "120",
            },
        ):
            import importlib

            import ui.backend.auth.rate_limit as mod

            importlib.reload(mod)
            assert mod.AUTH_RATE_LIMIT_MAX == 20
            assert mod.AUTH_RATE_LIMIT_WINDOW == 120

        # Reload back to defaults
        import importlib

        import ui.backend.auth.rate_limit as mod

        importlib.reload(mod)
