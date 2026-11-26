"""Tests for selecting the UX review and preparing its admin account."""

import io
import json
import secrets
import sys
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.ci import ux_review

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["ui/frontend/src/components/admin/LlmUsageManager.tsx"], "admin"),
        (["ui/frontend/src/App.css"], "admin"),
        (["ui/frontend/src/components/documents/SortableHeader.tsx"], "admin"),
        ([".github/review/ux/admin-session.cjs"], "admin-smoke"),
        (["scripts/ci/ux_review.py"], "admin-smoke"),
        (["ui/frontend/src/components/brief/brief.css"], "public"),
        (["docs/overview/about.md", "ui/backend/main.py"], "none"),
    ],
)
def test_review_scope_when_paths_change_then_selects_the_appropriate_review(
    paths, expected
):
    assert ux_review.review_scope(paths) == expected


def test_browser_config_when_admin_then_only_admin_browser_gets_session(tmp_path):
    session = tmp_path / "admin.json"
    template = json.loads(ux_review.MCP_TEMPLATE.read_text(encoding="utf-8"))
    guest = template["mcpServers"]["playwright"]

    config = ux_review.browser_config(template, session)["mcpServers"]

    assert config["playwright"] == guest
    assert "playwright_admin" not in template["mcpServers"]
    assert config["playwright_admin"]["args"] == [
        *guest["args"],
        "--storage-state",
        str(session),
    ]


def test_browser_config_when_public_then_only_guest_browser():
    template = {"mcpServers": {"playwright": {"args": []}}}

    assert ux_review.browser_config(template, None) == template


@pytest.mark.asyncio
async def test_create_admin_when_called_then_uses_application_user_manager(monkeypatch):
    from ui.backend.auth import db, users

    session_factory = Mock(return_value=AsyncMock(spec=AbstractAsyncContextManager))
    user_db = object()
    manager = Mock(create=AsyncMock())

    async def get_user_db(session):
        assert session is session_factory.return_value.__aenter__.return_value
        yield user_db

    monkeypatch.setattr(db, "async_session_factory", session_factory)
    monkeypatch.setattr(users, "get_user_db", get_user_db)
    user_manager = Mock(return_value=manager)
    monkeypatch.setattr(users, "UserManager", user_manager)
    password = secrets.token_hex(32)

    await ux_review.create_admin("ux-admin@example.org", password)

    user_manager.assert_called_once_with(user_db)
    manager.create.assert_awaited_once()
    user = manager.create.await_args.args[0]
    assert user.email == "ux-admin@example.org"
    assert user.password == password
    assert user.is_active and user.is_superuser and user.is_verified
    assert manager.create.await_args.kwargs == {"safe": False}


def test_main_when_scope_then_reads_nul_separated_paths(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ux_review", "scope"])
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("README.md\0ui/frontend/src/App.css\0")
    )

    ux_review.main()

    assert capsys.readouterr().out.strip() == "admin"


def test_main_when_browser_config_then_emits_json(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["ux_review", "browser-config", "--storage-state", "/tmp/ux"]
    )

    ux_review.main()

    config = json.loads(capsys.readouterr().out)
    assert config["mcpServers"]["playwright_admin"]["args"][-1] == str(Path("/tmp/ux"))
