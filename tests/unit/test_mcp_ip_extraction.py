"""Unit tests for MCP server IP extraction logic.

Verifies that _get_client_ip correctly prefers trusted proxy headers and
is not fooled by a client-controlled X-Forwarded-For prefix.
"""

import pytest

# ---------------------------------------------------------------------------
# Import helper — _get_client_ip lives in mcp_server.http_server but that
# module imports uvicorn and mcp SDK at the top level.  We import it via
# a targeted attribute access after importing the module (which requires the
# dependencies).  If the module can't be imported in the test environment,
# skip the tests gracefully.
# ---------------------------------------------------------------------------


def _import_get_client_ip():
    try:
        from mcp_server.http_server import _get_client_ip

        return _get_client_ip
    except ImportError as exc:
        pytest.skip(f"mcp_server.http_server not importable: {exc}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_prefers_x_real_ip_over_forwarded_for():
    """X-Real-IP (set by nginx $remote_addr) takes priority over X-Forwarded-For."""
    fn = _import_get_client_ip()
    scope = {
        "headers": [
            (b"x-real-ip", b"203.0.113.10"),
            (b"x-forwarded-for", b"1.2.3.4, 203.0.113.10"),
        ]
    }
    assert fn(scope) == "203.0.113.10"


def test_uses_rightmost_forwarded_for_when_no_real_ip():
    """When X-Real-IP is absent the rightmost X-Forwarded-For entry is used.

    The rightmost entry is added by our trusted proxy (nginx/Caddy); earlier
    entries are client-controlled and must not be trusted.
    """
    fn = _import_get_client_ip()
    scope = {
        "headers": [
            # Attacker claims to be 1.1.1.1 as leftmost entry
            (b"x-forwarded-for", b"1.1.1.1, 10.0.0.5, 172.16.0.1"),
        ]
    }
    # Should use 172.16.0.1 (rightmost, set by our proxy), not 1.1.1.1 (spoofed)
    assert fn(scope) == "172.16.0.1"


def test_spoofed_leftmost_forwarded_for_is_ignored():
    """A client spoofing the leftmost X-Forwarded-For entry cannot change their IP."""
    fn = _import_get_client_ip()
    scope = {
        "headers": [
            # No X-Real-IP — as if nginx is not in front
            (b"x-forwarded-for", b"192.168.0.1, 10.0.0.2"),
        ]
    }
    # Must use 10.0.0.2, not the spoofed 192.168.0.1
    assert fn(scope) != "192.168.0.1"
    assert fn(scope) == "10.0.0.2"


def test_falls_back_to_asgi_client_when_no_headers():
    """Falls back to ASGI client tuple when no proxy headers are present."""
    fn = _import_get_client_ip()
    scope = {
        "headers": [],
        "client": ("198.51.100.42", 54321),
    }
    assert fn(scope) == "198.51.100.42"


def test_returns_unknown_when_no_ip_available():
    """Returns 'unknown' when no IP can be determined."""
    fn = _import_get_client_ip()
    assert fn({"headers": []}) == "unknown"


def test_single_forwarded_for_entry():
    """A single X-Forwarded-For entry is used directly."""
    fn = _import_get_client_ip()
    scope = {"headers": [(b"x-forwarded-for", b"198.51.100.5")]}
    assert fn(scope) == "198.51.100.5"
