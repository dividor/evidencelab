"""Unit tests for user management routes (ui/backend/routes/users.py).

These tests mock the database session and FastAPI dependencies to test
route handler logic in isolation.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.backend.routes.users import (
    admin_delete_user,
    delete_my_account,
    get_my_groups,
    list_users,
    update_user_flags,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    email="admin@test.com",
    is_superuser=True,
    display_name=None,
):
    """Create a mock User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.is_superuser = is_superuser
    user.is_active = True
    user.is_verified = True
    user.display_name = display_name
    return user


def _make_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _mock_execute_result(items):
    """Create a mock result from session.execute()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalars.return_value.first.return_value = items[0] if items else None
    result.unique.return_value = result
    return result


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


class TestListUsers:
    """Tests for GET /users/all."""

    @pytest.mark.asyncio
    async def test_returns_all_users(self):
        """Superuser should get a list of all users."""
        admin = _make_user()
        user1 = _make_user(email="user1@test.com")
        user2 = _make_user(email="user2@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([user1, user2]))

        result = await list_users(admin=admin, session=session)
        assert len(result) == 2
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_users(self):
        """Should return empty list when no users exist."""
        admin = _make_user()
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([]))

        result = await list_users(admin=admin, session=session)
        assert result == []


# ---------------------------------------------------------------------------
# update_user_flags
# ---------------------------------------------------------------------------


class TestUpdateUserFlags:
    """Tests for PATCH /users/{user_id}/flags."""

    @pytest.mark.asyncio
    async def test_updates_is_active(self):
        """Should update the is_active flag."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        result = await update_user_flags(
            user_id=target.id,
            is_active=False,
            is_verified=None,
            is_superuser=None,
            admin=admin,
            session=session,
        )
        assert result.is_active is False
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_is_verified(self):
        """Should update the is_verified flag."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        await update_user_flags(
            user_id=target.id,
            is_active=None,
            is_verified=True,
            is_superuser=None,
            admin=admin,
            session=session,
        )
        assert target.is_verified is True

    @pytest.mark.asyncio
    async def test_updates_is_superuser(self):
        """Should update the is_superuser flag."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        await update_user_flags(
            user_id=target.id,
            is_active=None,
            is_verified=None,
            is_superuser=True,
            admin=admin,
            session=session,
        )
        assert target.is_superuser is True

    @pytest.mark.asyncio
    async def test_404_when_user_not_found(self):
        """Should raise 404 when user doesn't exist."""
        from fastapi import HTTPException

        admin = _make_user()
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([]))

        with pytest.raises(HTTPException) as exc:
            await update_user_flags(
                user_id=uuid.uuid4(),
                is_active=True,
                is_verified=None,
                is_superuser=None,
                admin=admin,
                session=session,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_updates_multiple_flags(self):
        """Should update multiple flags in one call."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        target.is_active = True
        target.is_verified = False
        target.is_superuser = False
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        await update_user_flags(
            user_id=target.id,
            is_active=False,
            is_verified=True,
            is_superuser=True,
            admin=admin,
            session=session,
        )
        assert target.is_active is False
        assert target.is_verified is True
        assert target.is_superuser is True

    @pytest.mark.asyncio
    async def test_no_update_when_all_none(self):
        """Passing all None flags should commit without changing anything."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        original_active = target.is_active
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        await update_user_flags(
            user_id=target.id,
            is_active=None,
            is_verified=None,
            is_superuser=None,
            admin=admin,
            session=session,
        )
        assert target.is_active == original_active


# ---------------------------------------------------------------------------
# admin_delete_user
# ---------------------------------------------------------------------------


class TestAdminDeleteUser:
    """Tests for DELETE /users/{user_id}."""

    @pytest.mark.asyncio
    async def test_deletes_user(self):
        """Should delete a user and return confirmation."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        result = await admin_delete_user(
            user_id=target.id, admin=admin, session=session
        )
        assert "deleted" in result["detail"].lower()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cannot_delete_self(self):
        """Admin should not be able to delete their own account via this route."""
        from fastapi import HTTPException

        admin = _make_user()
        session = _make_session()

        with pytest.raises(HTTPException) as exc:
            await admin_delete_user(user_id=admin.id, admin=admin, session=session)
        assert exc.value.status_code == 400
        assert "own account" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_404_when_user_not_found(self):
        """Should raise 404 when user doesn't exist."""
        from fastapi import HTTPException

        admin = _make_user()
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([]))

        with pytest.raises(HTTPException) as exc:
            await admin_delete_user(user_id=uuid.uuid4(), admin=admin, session=session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cleans_up_related_data(self):
        """Should delete group memberships, OAuth links, and anonymise audit logs."""
        admin = _make_user()
        target = _make_user(email="target@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=_mock_execute_result([target]))

        await admin_delete_user(user_id=target.id, admin=admin, session=session)
        # Should have multiple execute calls: find user, delete memberships,
        # delete OAuth, anonymise audit, delete user
        assert session.execute.call_count >= 4


# ---------------------------------------------------------------------------
# get_my_groups
# ---------------------------------------------------------------------------


class TestGetMyGroups:
    """Tests for GET /users/me/groups."""

    @pytest.mark.asyncio
    async def test_returns_user_groups(self):
        """Should return groups the user belongs to."""
        user = _make_user(email="user@test.com")
        group1 = MagicMock()
        group1.id = uuid.uuid4()
        group1.name = "Group A"
        group1.description = "Desc A"
        group2 = MagicMock()
        group2.id = uuid.uuid4()
        group2.name = "Group B"
        group2.description = None

        session = _make_session()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [group1, group2]
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_my_groups(user=user, session=session)
        assert len(result) == 2
        assert result[0]["name"] == "Group A"
        assert result[1]["name"] == "Group B"
        assert result[1]["description"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_groups(self):
        """Should return empty list when user has no group memberships."""
        user = _make_user(email="user@test.com")
        session = _make_session()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_my_groups(user=user, session=session)
        assert result == []


# ---------------------------------------------------------------------------
# delete_my_account
# ---------------------------------------------------------------------------


class TestDeleteMyAccount:
    """Tests for DELETE /users/me/account."""

    @pytest.mark.asyncio
    async def test_deletes_own_account(self):
        """Should delete the current user's account."""
        user = _make_user(email="selfdelete@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        response = MagicMock()

        with patch("ui.backend.routes.users.write_audit_event", new_callable=AsyncMock):
            result = await delete_my_account(
                response=response, user=user, session=session
            )

        assert "deleted" in result["detail"].lower()
        session.commit.assert_called_once()
        response.delete_cookie.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_auth_cookie(self):
        """Should clear the evidencelab_auth cookie."""
        user = _make_user(email="selfdelete@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        response = MagicMock()

        with patch("ui.backend.routes.users.write_audit_event", new_callable=AsyncMock):
            await delete_my_account(response=response, user=user, session=session)

        response.delete_cookie.assert_called_once_with(
            "evidencelab_auth",
            httponly=True,
            samesite="lax",
        )

    @pytest.mark.asyncio
    async def test_writes_audit_event_before_delete(self):
        """Should write an audit event before deleting the user."""
        user = _make_user(email="selfdelete@test.com")
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        response = MagicMock()

        with patch(
            "ui.backend.routes.users.write_audit_event", new_callable=AsyncMock
        ) as mock_audit:
            await delete_my_account(response=response, user=user, session=session)

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs[0][0] == "account_deleted"
        assert call_kwargs[1]["user_email"] == "selfdelete@test.com"
