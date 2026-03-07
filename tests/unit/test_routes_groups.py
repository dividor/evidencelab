"""Unit tests for group management routes (ui/backend/routes/groups.py).

These tests mock the database session and FastAPI dependencies to test
route handler logic in isolation.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from ui.backend.auth.schemas import (
    GroupCreate,
    GroupDatasourceSet,
    GroupMemberAdd,
    GroupUpdate,
)
from ui.backend.routes.groups import (
    add_group_member,
    create_group,
    delete_group,
    get_group,
    list_datasource_keys,
    list_group_members,
    list_groups,
    remove_group_member,
    set_group_datasources,
    update_group,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin():
    """Create a mock admin User."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@test.com"
    user.is_superuser = True
    return user


def _make_group(
    *,
    name="Test Group",
    description=None,
    is_default=False,
    search_settings=None,
    summary_prompt=None,
):
    """Create a mock UserGroup."""
    group = MagicMock()
    group.id = uuid.uuid4()
    group.name = name
    group.description = description
    group.is_default = is_default
    group.created_at = "2024-01-01T00:00:00Z"
    group.search_settings = search_settings
    group.summary_prompt = summary_prompt
    return group


def _make_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def _scalars_result(items):
    """Build a mock Result that returns items from .scalars().all() and .first()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalars.return_value.first.return_value = items[0] if items else None
    result.scalar.return_value = len(items)
    result.unique.return_value = result
    return result


# ---------------------------------------------------------------------------
# list_groups
# ---------------------------------------------------------------------------


class TestListGroups:
    """Tests for GET /groups/."""

    @pytest.mark.asyncio
    async def test_returns_groups(self):
        """Should return all groups."""
        admin = _make_admin()
        g1 = _make_group(name="Alpha")
        g2 = _make_group(name="Beta")
        session = _make_session()

        # list_groups calls execute once for the groups query,
        # then _group_to_read calls execute twice per group (datasources + count)
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Groups query
                return _scalars_result([g1, g2])
            # Datasource / member count queries
            return _scalars_result([])

        session.execute = mock_execute

        result = await list_groups(admin=admin, session=session)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        """Should return empty list when no groups exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))

        result = await list_groups(admin=admin, session=session)
        assert result == []


# ---------------------------------------------------------------------------
# create_group
# ---------------------------------------------------------------------------


class TestCreateGroup:
    """Tests for POST /groups/."""

    @pytest.mark.asyncio
    async def test_creates_group(self):
        """Should create a new group and return it."""
        admin = _make_admin()
        session = _make_session()
        body = GroupCreate(name="New Group", description="A description")

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            return _scalars_result([])

        session.execute = mock_execute

        # session.refresh needs to populate the ORM object with defaults
        async def mock_refresh(obj):
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid.uuid4()
            if not hasattr(obj, "is_default") or obj.is_default is None:
                obj.is_default = False
            if not hasattr(obj, "created_at") or obj.created_at is None:
                from datetime import datetime, timezone

                obj.created_at = datetime.now(timezone.utc)

        session.refresh = mock_refresh

        result = await create_group(body=body, admin=admin, session=session)
        assert result.name == "New Group"


# ---------------------------------------------------------------------------
# get_group
# ---------------------------------------------------------------------------


class TestGetGroup:
    """Tests for GET /groups/{group_id}."""

    @pytest.mark.asyncio
    async def test_returns_group(self):
        """Should return a single group by ID."""
        admin = _make_admin()
        group = _make_group(name="My Group")
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])
            return _scalars_result([])

        session.execute = mock_execute

        result = await get_group(group_id=group.id, admin=admin, session=session)
        assert result.name == "My Group"

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        """Should raise 404 when group doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))

        with pytest.raises(HTTPException) as exc:
            await get_group(group_id=uuid.uuid4(), admin=admin, session=session)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# update_group
# ---------------------------------------------------------------------------


class TestUpdateGroup:
    """Tests for PATCH /groups/{group_id}."""

    @pytest.mark.asyncio
    async def test_updates_name(self):
        """Should update the group name."""
        admin = _make_admin()
        group = _make_group(name="Old Name")
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])
            return _scalars_result([])

        session.execute = mock_execute
        body = GroupUpdate(name="New Name")

        await update_group(group_id=group.id, body=body, admin=admin, session=session)
        assert group.name == "New Name"
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_description(self):
        """Should update the group description."""
        admin = _make_admin()
        group = _make_group(name="Group", description="Old desc")
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])
            return _scalars_result([])

        session.execute = mock_execute
        body = GroupUpdate(description="New description")

        await update_group(group_id=group.id, body=body, admin=admin, session=session)
        assert group.description == "New description"

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        """Should raise 404 when group doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        body = GroupUpdate(name="Updated")

        with pytest.raises(HTTPException) as exc:
            await update_group(
                group_id=uuid.uuid4(), body=body, admin=admin, session=session
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_group
# ---------------------------------------------------------------------------


class TestDeleteGroup:
    """Tests for DELETE /groups/{group_id}."""

    @pytest.mark.asyncio
    async def test_deletes_group(self):
        """Should delete a non-default group."""
        admin = _make_admin()
        group = _make_group(name="Delete Me", is_default=False)
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([group]))

        await delete_group(group_id=group.id, admin=admin, session=session)
        session.delete.assert_called_once_with(group)
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cannot_delete_default_group(self):
        """Should reject deletion of the default group."""
        admin = _make_admin()
        group = _make_group(name="Default", is_default=True)
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([group]))

        with pytest.raises(HTTPException) as exc:
            await delete_group(group_id=group.id, admin=admin, session=session)
        assert exc.value.status_code == 400
        assert "default" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        """Should raise 404 when group doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))

        with pytest.raises(HTTPException) as exc:
            await delete_group(group_id=uuid.uuid4(), admin=admin, session=session)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_group_members
# ---------------------------------------------------------------------------


class TestListGroupMembers:
    """Tests for GET /groups/{group_id}/members."""

    @pytest.mark.asyncio
    async def test_returns_members(self):
        """Should return a list of group members."""
        admin = _make_admin()
        session = _make_session()

        user1 = MagicMock()
        user1.id = uuid.uuid4()
        user1.email = "user1@test.com"
        user1.full_name = "User One"
        user1.is_active = True

        user2 = MagicMock()
        user2.id = uuid.uuid4()
        user2.email = "user2@test.com"
        user2.full_name = None
        user2.is_active = False

        session.execute = AsyncMock(return_value=_scalars_result([user1, user2]))

        result = await list_group_members(
            group_id=uuid.uuid4(), admin=admin, session=session
        )
        assert len(result) == 2
        assert result[0]["email"] == "user1@test.com"
        assert result[0]["display_name"] == "User One"
        assert result[1]["is_active"] is False

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_members(self):
        """Should return empty list when group has no members."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))

        result = await list_group_members(
            group_id=uuid.uuid4(), admin=admin, session=session
        )
        assert result == []


# ---------------------------------------------------------------------------
# add_group_member
# ---------------------------------------------------------------------------


class TestAddGroupMember:
    """Tests for POST /groups/{group_id}/members."""

    @pytest.mark.asyncio
    async def test_adds_member(self):
        """Should add a user to the group."""
        admin = _make_admin()
        group = _make_group()
        user = MagicMock()
        user.id = uuid.uuid4()
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])  # group exists
            if call_count == 2:
                return _scalars_result([user])  # user exists
            return _scalars_result([])  # no existing membership

        session.execute = mock_execute
        body = GroupMemberAdd(user_id=user.id)

        result = await add_group_member(
            group_id=group.id, body=body, admin=admin, session=session
        )
        assert result["status"] == "added"
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_when_group_not_found(self):
        """Should raise 404 when group doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        body = GroupMemberAdd(user_id=uuid.uuid4())

        with pytest.raises(HTTPException) as exc:
            await add_group_member(
                group_id=uuid.uuid4(), body=body, admin=admin, session=session
            )
        assert exc.value.status_code == 404
        assert "group" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_404_when_user_not_found(self):
        """Should raise 404 when user doesn't exist."""
        admin = _make_admin()
        group = _make_group()
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])  # group exists
            return _scalars_result([])  # user not found

        session.execute = mock_execute
        body = GroupMemberAdd(user_id=uuid.uuid4())

        with pytest.raises(HTTPException) as exc:
            await add_group_member(
                group_id=group.id, body=body, admin=admin, session=session
            )
        assert exc.value.status_code == 404
        assert "user" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_409_when_already_member(self):
        """Should raise 409 when user is already in the group."""
        admin = _make_admin()
        group = _make_group()
        user = MagicMock()
        user.id = uuid.uuid4()
        existing = MagicMock()
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])  # group exists
            if call_count == 2:
                return _scalars_result([user])  # user exists
            return _scalars_result([existing])  # existing membership

        session.execute = mock_execute
        body = GroupMemberAdd(user_id=user.id)

        with pytest.raises(HTTPException) as exc:
            await add_group_member(
                group_id=group.id, body=body, admin=admin, session=session
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# remove_group_member
# ---------------------------------------------------------------------------


class TestRemoveGroupMember:
    """Tests for DELETE /groups/{group_id}/members/{user_id}."""

    @pytest.mark.asyncio
    async def test_removes_member(self):
        """Should remove a user from the group."""
        admin = _make_admin()
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 1
        session.execute = AsyncMock(return_value=result_mock)

        await remove_group_member(
            group_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            admin=admin,
            session=session,
        )
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_when_membership_not_found(self):
        """Should raise 404 when membership doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc:
            await remove_group_member(
                group_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                admin=admin,
                session=session,
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# set_group_datasources
# ---------------------------------------------------------------------------


class TestSetGroupDatasources:
    """Tests for PUT /groups/{group_id}/datasources."""

    @pytest.mark.asyncio
    async def test_sets_datasources(self):
        """Should replace datasource grants."""
        admin = _make_admin()
        group = _make_group()
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])  # group exists
            return _scalars_result([])  # delete existing / re-read

        session.execute = mock_execute
        body = GroupDatasourceSet(datasource_keys=["UNEG", "ACLED"])

        await set_group_datasources(
            group_id=group.id, body=body, admin=admin, session=session
        )
        session.commit.assert_called_once()
        # session.add should be called twice (one per datasource key)
        assert session.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_sets_empty_datasources(self):
        """Should allow setting empty datasource list (no access)."""
        admin = _make_admin()
        group = _make_group()
        session = _make_session()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([group])
            return _scalars_result([])

        session.execute = mock_execute
        body = GroupDatasourceSet(datasource_keys=[])

        await set_group_datasources(
            group_id=group.id, body=body, admin=admin, session=session
        )
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_when_group_not_found(self):
        """Should raise 404 when group doesn't exist."""
        admin = _make_admin()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalars_result([]))
        body = GroupDatasourceSet(datasource_keys=["UNEG"])

        with pytest.raises(HTTPException) as exc:
            await set_group_datasources(
                group_id=uuid.uuid4(), body=body, admin=admin, session=session
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_datasource_keys
# ---------------------------------------------------------------------------


class TestListDatasourceKeys:
    """Tests for GET /groups/datasource-keys."""

    @pytest.mark.asyncio
    async def test_returns_datasource_keys(self):
        """Should return list of configured datasource keys."""
        admin = _make_admin()

        mock_config = {
            "datasources": {
                "UNEG": {"data_subdir": "uneg"},
                "ACLED": {"data_subdir": "acled"},
            }
        }
        # The function does a lazy `import pipeline.db as pipeline_db`,
        # so we patch load_datasources_config on the real module.
        with patch("pipeline.db.load_datasources_config", return_value=mock_config):
            result = await list_datasource_keys(admin=admin)
            assert set(result) == {"UNEG", "ACLED"}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_datasources(self):
        """Should return empty list when no datasources configured."""
        admin = _make_admin()

        mock_config = {"datasources": {}}
        with patch("pipeline.db.load_datasources_config", return_value=mock_config):
            result = await list_datasource_keys(admin=admin)
            assert result == []
