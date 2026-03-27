"""Ensure every fetch(API_BASE_URL/...) call includes credentials: 'include'.

Without credentials, requests to authenticated endpoints fail with 401
when ActiveAuthMiddleware is enabled. This test scans all frontend
source files and flags fetch calls that are missing the credential.
"""

import re
from pathlib import Path

import pytest

SRC_DIR = Path("ui/frontend/src")

# Paths that are exempt from auth (match EXEMPT_PATH_PREFIXES in active_auth.py)
EXEMPT_PATHS = (
    "/auth/",
    "/config/",
    "/health",
    "/users/",
    "/groups/",
    "/ratings/",
    "/activity/",
    "/api-keys",
)


def _find_fetch_calls_missing_credentials():
    """Return list of (file, line_number, line) for fetch calls without credentials."""
    issues = []
    for ts_file in SRC_DIR.rglob("*.ts*"):
        if "node_modules" in str(ts_file) or ".test." in str(ts_file):
            continue
        lines = ts_file.read_text().splitlines()
        for i, line in enumerate(lines):
            # Match fetch(`${API_BASE_URL}/...
            if re.search(r"fetch\(\`\$\{API_BASE_URL\}", line):
                # Check if the URL is an exempt path
                exempt = any(f'/{p.strip("/")}' in line for p in EXEMPT_PATHS)
                if exempt:
                    continue
                # Look in the next 5 lines for credentials: 'include'
                block = "\n".join(lines[i : i + 6])
                if "credentials" not in block:
                    issues.append((str(ts_file), i + 1, line.strip()))
    return issues


def _find_fetch_calls_missing_api_key():
    """Return list of (file, line_number, line) for fetch calls without X-API-Key."""
    issues = []
    for ts_file in SRC_DIR.rglob("*.ts*"):
        if "node_modules" in str(ts_file) or ".test." in str(ts_file):
            continue
        lines = ts_file.read_text().splitlines()
        for i, line in enumerate(lines):
            if re.search(r"fetch\(\`\$\{API_BASE_URL\}", line):
                exempt = any(f'/{p.strip("/")}' in line for p in EXEMPT_PATHS)
                if exempt:
                    continue
                # Look in surrounding context (headers may be built above)
                start = max(0, i - 10)
                block = "\n".join(lines[start : i + 8])
                if "X-API-Key" not in block:
                    issues.append((str(ts_file), i + 1, line.strip()))
    return issues


def test_all_api_fetch_calls_include_credentials():
    """Every fetch to API_BASE_URL must include credentials: 'include'."""
    issues = _find_fetch_calls_missing_credentials()
    if issues:
        msg = "fetch() calls missing credentials: 'include':\n"
        for path, lineno, line in issues:
            msg += f"  {path}:{lineno}: {line}\n"
        pytest.fail(msg)


def test_all_api_fetch_calls_include_api_key():
    """Every fetch to API_BASE_URL must include X-API-Key header."""
    issues = _find_fetch_calls_missing_api_key()
    if issues:
        msg = "fetch() calls missing X-API-Key header:\n"
        for path, lineno, line in issues:
            msg += f"  {path}:{lineno}: {line}\n"
        pytest.fail(msg)
