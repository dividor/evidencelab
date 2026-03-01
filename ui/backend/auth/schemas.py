"""Pydantic schemas for user authentication and permissions."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi_users import schemas
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# fastapi-users schemas (registration, login, profile)
# ---------------------------------------------------------------------------


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Public user representation returned by read endpoints."""

    display_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserCreate(schemas.BaseUserCreate):
    """Fields accepted when registering a new user."""

    display_name: Optional[str] = None


class UserUpdate(schemas.BaseUserUpdate):
    """Fields accepted when updating the current user's profile."""

    display_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Group & permission schemas
# ---------------------------------------------------------------------------


class GroupBase(BaseModel):
    """Shared group fields."""

    name: str
    description: Optional[str] = None


class GroupCreate(GroupBase):
    """Fields for creating a new group."""


class GroupUpdate(BaseModel):
    """Fields for updating an existing group."""

    name: Optional[str] = None
    description: Optional[str] = None


class GroupRead(GroupBase):
    """Group representation returned by read endpoints."""

    id: uuid.UUID
    is_default: bool
    created_at: datetime
    datasource_keys: list[str] = []
    member_count: int = 0

    model_config = {"from_attributes": True}


class GroupMemberAdd(BaseModel):
    """Payload for adding a user to a group."""

    user_id: uuid.UUID


class GroupDatasourceSet(BaseModel):
    """Payload for setting the datasource keys a group can access."""

    datasource_keys: list[str]
