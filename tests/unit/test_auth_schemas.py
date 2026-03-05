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
        assert user.first_name is None
        assert user.last_name is None

    def test_user_create_with_name(self):
        user = UserCreate(
            email="test@example.com",
            password="securepass",  # pragma: allowlist secret
            first_name="Test",
            last_name="User",
        )
        assert user.first_name == "Test"
        assert user.last_name == "User"

    def test_user_create_missing_email_fails(self):
        with pytest.raises(ValidationError):
            UserCreate(password="securepass")  # pragma: allowlist secret

    def test_user_create_missing_password_fails(self):
        with pytest.raises(ValidationError):
            UserCreate(email="test@example.com")

    def test_user_update_all_optional(self):
        update = UserUpdate()
        assert update.first_name is None
        assert update.last_name is None

    def test_user_update_with_name(self):
        update = UserUpdate(first_name="New", last_name="Name")
        assert update.first_name == "New"
        assert update.last_name == "Name"

    def test_user_read_includes_timestamps(self):
        user_id = uuid.uuid4()
        user = UserRead(
            id=user_id,
            email="test@example.com",
            is_active=True,
            is_verified=False,
            is_superuser=False,
            first_name="Test",
            last_name="User",
            created_at=None,
            updated_at=None,
        )
        assert user.display_name == "Test User"
        assert user.first_name == "Test"
        assert user.id == user_id

    def test_user_read_display_name_computed(self):
        """display_name is computed from first_name + last_name."""
        user = UserRead(
            id=uuid.uuid4(),
            email="a@b.com",
            is_active=True,
            is_verified=False,
            is_superuser=False,
            first_name="Alice",
            last_name=None,
        )
        assert user.display_name == "Alice"

    def test_user_read_display_name_none_when_no_names(self):
        """display_name is None when both first_name and last_name are None."""
        user = UserRead(
            id=uuid.uuid4(),
            email="a@b.com",
            is_active=True,
            is_verified=False,
            is_superuser=False,
        )
        assert user.display_name is None


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


class TestNameFieldValidation:
    """Tests for first_name / last_name field validation on UserCreate and UserUpdate."""

    def test_first_name_max_length_enforced_on_create(self):
        """first_name longer than 255 chars should be rejected."""
        long_name = "A" * 256
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                email="test@example.com",
                password="Secure1Pass",  # pragma: allowlist secret
                first_name=long_name,
            )
        assert "first_name" in str(exc.value)

    def test_last_name_max_length_enforced_on_update(self):
        """last_name longer than 255 chars should be rejected on update."""
        long_name = "A" * 256
        with pytest.raises(ValidationError) as exc:
            UserUpdate(last_name=long_name)
        assert "last_name" in str(exc.value)

    def test_first_name_255_chars_accepted(self):
        """first_name exactly at the 255-char limit should be accepted."""
        name = "A" * 255
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            first_name=name,
        )
        assert user.first_name == name

    def test_first_name_whitespace_stripped_on_create(self):
        """Leading/trailing whitespace should be stripped."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            first_name="  Alice  ",
        )
        assert user.first_name == "Alice"

    def test_last_name_whitespace_stripped_on_update(self):
        """Leading/trailing whitespace should be stripped on update."""
        update = UserUpdate(last_name="  Baker  ")
        assert update.last_name == "Baker"

    def test_first_name_blank_becomes_none_on_create(self):
        """A whitespace-only first_name should become None."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            first_name="   ",
        )
        assert user.first_name is None

    def test_last_name_blank_becomes_none_on_update(self):
        """A whitespace-only last_name should become None on update."""
        update = UserUpdate(last_name="  ")
        assert update.last_name is None

    def test_first_name_none_stays_none(self):
        """Explicitly passing None should remain None."""
        user = UserCreate(
            email="test@example.com",
            password="Secure1Pass",  # pragma: allowlist secret
            first_name=None,
        )
        assert user.first_name is None

    def test_last_name_empty_string_becomes_none(self):
        """Empty string last_name should become None after strip."""
        update = UserUpdate(last_name="")
        assert update.last_name is None
