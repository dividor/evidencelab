"""Unit tests for async permission functions (get_user_datasource_keys, add_user_to_default_group).

These functions interact with the database, so we mock the AsyncSession.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ui.backend.services.permissions import (
    add_user_to_default_group,
    get_user_datasource_keys,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _scalars_result(items):
    """Build a mock Result that returns items from .scalars().all() and .first()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalars.return_value.first.return_value = items[0] if items else None
    return result


# ---------------------------------------------------------------------------
# get_user_datasource_keys
# ---------------------------------------------------------------------------


class TestGetUserDatasourceKeys:
    """Tests for the get_user_datasource_keys function."""

    @pytest.mark.asyncio
    async def test_returns_datasource_keys_from_groups(self):
        """Should return the union of datasource keys from all user groups."""
        session = _make_session()
        session.execute = AsyncMock(
            return_value=_scalars_result(["UNEG", "ACLED", "OCHA"])
        )
        user_id = uuid.uuid4()

        result = await get_user_datasource_keys(session, user_id)
        assert result == {"UNEG", "ACLED", "OCHA"}
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_set_when_no_access(self):
        """Should return empty set when user has no datasource grants."""
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        user_id = uuid.uuid4()

        result = await get_user_datasource_keys(session, user_id)
        assert result == set()

    @pytest.mark.asyncio
    async def test_deduplicates_across_groups(self):
        """Should return unique keys even if multiple groups grant the same."""
        session = _make_session()
        session.execute = AsyncMock(
            return_value=_scalars_result(["UNEG", "UNEG", "ACLED"])
        )
        user_id = uuid.uuid4()

        result = await get_user_datasource_keys(session, user_id)
        assert result == {"UNEG", "ACLED"}


# ---------------------------------------------------------------------------
# add_user_to_default_group
# ---------------------------------------------------------------------------


class TestAddUserToDefaultGroup:
    """Tests for the add_user_to_default_group function."""

    @pytest.mark.asyncio
    async def test_adds_user_to_default_group(self):
        """Should create a membership for the user in the default group."""
        session = _make_session()
        default_group = MagicMock()
        default_group.id = uuid.uuid4()
        session.execute = AsyncMock(return_value=_scalars_result([default_group]))
        user_id = uuid.uuid4()

        await add_user_to_default_group(session, user_id)
        session.add.assert_called_once()
        session.commit.assert_called_once()

        # Verify the membership has the right IDs
        membership = session.add.call_args[0][0]
        assert membership.user_id == user_id
        assert membership.group_id == default_group.id

    @pytest.mark.asyncio
    async def test_noop_when_no_default_group(self):
        """Should do nothing when no default group exists."""
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        user_id = uuid.uuid4()

        await add_user_to_default_group(session, user_id)
        session.add.assert_not_called()
        session.commit.assert_not_called()
