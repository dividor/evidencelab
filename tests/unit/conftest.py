import pytest

"""
Pytest configuration for test suite
"""

import sys
from pathlib import Path

# Add project root to path so tests can import project modules
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


@pytest.fixture
def one_data_source(monkeypatch):
    """A deployment with one data source, so a request may name none."""
    from pipeline.db import config as db_config

    monkeypatch.setattr(db_config, "_configured_data_sources", lambda: ["uneg"])


class _SpentTodaySession:
    """Async session stub whose day's AI total is ``spent``."""

    def __init__(self, spent):
        self.spent = spent

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.scalar_one_or_none.return_value = self.spent
        return result


@pytest.fixture
def ai_limit_reached(monkeypatch):
    """The site's daily AI limit (AI_DAILY_COST_LIMIT_USD) is used up.

    The real check runs; only the database answering "today's total" is a
    stub, and the check's cache starts empty.
    """
    from decimal import Decimal

    from ui.backend.services import ai_daily_limit

    monkeypatch.setenv(ai_daily_limit.LIMIT_ENV, "1")
    monkeypatch.setattr(
        ai_daily_limit,
        "_cache",
        {"day": None, "spent": Decimal(0), "read_at": float("-inf")},
    )
    monkeypatch.setattr(
        "ui.backend.auth.db.async_session_factory",
        lambda: _SpentTodaySession(Decimal("1")),
    )
