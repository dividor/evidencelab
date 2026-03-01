"""Unit tests for auth Pydantic schemas."""

import uuid

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    GroupCreate,
    GroupDatasourceSet,
    GroupMemberAdd,
    GroupRead,
    GroupUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)


class TestUserSchemas:
    """Tests for user-related Pydantic schemas."""

    def test_user_create_minimal(self):
        user = UserCreate(email="test@example.com", password="securepass")
        assert user.email == "test@example.com"
        assert user.display_name is None

    def test_user_create_with_display_name(self):
        user = UserCreate(
            email="test@example.com",
            password="securepass",
            display_name="Test User",
        )
        assert user.display_name == "Test User"

    def test_user_create_missing_email_fails(self):
        with pytest.raises(ValidationError):
            UserCreate(password="securepass")

    def test_user_create_missing_password_fails(self):
        with pytest.raises(ValidationError):
            UserCreate(email="test@example.com")

    def test_user_update_all_optional(self):
        update = UserUpdate()
        assert update.display_name is None

    def test_user_update_with_name(self):
        update = UserUpdate(display_name="New Name")
        assert update.display_name == "New Name"

    def test_user_read_includes_timestamps(self):
        user_id = uuid.uuid4()
        user = UserRead(
            id=user_id,
            email="test@example.com",
            is_active=True,
            is_verified=False,
            is_superuser=False,
            display_name="Test",
            created_at=None,
            updated_at=None,
        )
        assert user.display_name == "Test"
        assert user.id == user_id


class TestGroupSchemas:
    """Tests for group-related Pydantic schemas."""

    def test_group_create(self):
        group = GroupCreate(name="Analysts", description="Data analysts")
        assert group.name == "Analysts"
        assert group.description == "Data analysts"

    def test_group_create_name_required(self):
        with pytest.raises(ValidationError):
            GroupCreate(description="No name")

    def test_group_update_all_optional(self):
        update = GroupUpdate()
        assert update.name is None
        assert update.description is None

    def test_group_read(self):
        group_id = uuid.uuid4()
        group = GroupRead(
            id=group_id,
            name="Default",
            description="Default group",
            is_default=True,
            created_at="2026-01-01T00:00:00Z",
            datasource_keys=["A", "B"],
            member_count=5,
        )
        assert group.is_default is True
        assert len(group.datasource_keys) == 2
        assert group.member_count == 5

    def test_group_member_add(self):
        user_id = uuid.uuid4()
        body = GroupMemberAdd(user_id=user_id)
        assert body.user_id == user_id

    def test_group_datasource_set(self):
        body = GroupDatasourceSet(datasource_keys=["UN Reports", "World Bank"])
        assert len(body.datasource_keys) == 2

    def test_group_datasource_set_empty(self):
        body = GroupDatasourceSet(datasource_keys=[])
        assert body.datasource_keys == []
