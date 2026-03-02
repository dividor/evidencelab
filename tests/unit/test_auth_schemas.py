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
        pw = "securepass"  # pragma: allowlist secret
        user = UserCreate(email="test@example.com", password=pw)
        assert user.email == "test@example.com"
        assert user.display_name is None

    def test_user_create_with_display_name(self):
        user = UserCreate(
            email="test@example.com",
            password="securepass",  # pragma: allowlist secret
            display_name="Test User",
        )
        assert user.display_name == "Test User"

    def test_user_create_missing_email_fails(self):
        with pytest.raises(ValidationError):
            UserCreate(password="securepass")  # pragma: allowlist secret

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


class TestDisplayNameValidation:
    """Tests for display_name field validation on UserCreate and UserUpdate."""

    def test_display_name_max_length_enforced_on_create(self):
        """display_name longer than 255 chars should be rejected."""
        long_name = "A" * 256
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                email="test@example.com",
                password="Secure1Pass",  # pragma: allowlist secret
                display_name=long_name,
            )
        assert "display_name" in str(exc.value)

    def test_display_name_max_length_enforced_on_update(self):
        """display_name longer than 255 chars should be rejected on update."""
        long_name = "A" * 256
        with pytest.raises(ValidationError) as exc:
            UserUpdate(display_name=long_name)
        assert "display_name" in str(exc.value)

    def test_display_name_255_chars_accepted(self):
        """display_name exactly at the 255-char limit should be accepted."""
        name = "A" * 255
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            display_name=name,
        )
        assert user.display_name == name

    def test_display_name_whitespace_stripped_on_create(self):
        """Leading/trailing whitespace should be stripped."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            display_name="  Alice Baker  ",
        )
        assert user.display_name == "Alice Baker"

    def test_display_name_whitespace_stripped_on_update(self):
        """Leading/trailing whitespace should be stripped on update."""
        update = UserUpdate(display_name="  Bob  ")
        assert update.display_name == "Bob"

    def test_display_name_blank_becomes_none_on_create(self):
        """A whitespace-only display_name should become None."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            display_name="   ",
        )
        assert user.display_name is None

    def test_display_name_blank_becomes_none_on_update(self):
        """A whitespace-only display_name should become None on update."""
        update = UserUpdate(display_name="  ")
        assert update.display_name is None

    def test_display_name_none_stays_none(self):
        """Explicitly passing None should remain None."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            display_name=None,
        )
        assert user.display_name is None

    def test_display_name_empty_string_becomes_none(self):
        """Empty string display_name should become None after strip."""
        update = UserUpdate(display_name="")
        assert update.display_name is None
