"""User management routes — profile, user listing (admin)."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import User, UserGroup, UserGroupMember
from ui.backend.auth.schemas import UserRead, UserUpdate
from ui.backend.auth.users import current_active_user, current_superuser, fastapi_users

router = APIRouter()

# fastapi-users provides GET /me, PATCH /me, DELETE /me
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    tags=["users"],
)


# ---------------------------------------------------------------------------
# Admin: list all users
# ---------------------------------------------------------------------------


@router.get("/all", response_model=List[UserRead], tags=["users"])
async def list_users(
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all users (superuser only)."""
    result = await session.execute(select(User).order_by(User.email))
    users = result.scalars().all()
    return users


# ---------------------------------------------------------------------------
# Admin: toggle user flags
# ---------------------------------------------------------------------------


@router.patch("/{user_id}/flags", response_model=UserRead, tags=["users"])
async def update_user_flags(
    user_id: uuid.UUID,
    is_active: bool | None = None,
    is_verified: bool | None = None,
    is_superuser: bool | None = None,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Update user flags (superuser only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if is_active is not None:
        user.is_active = is_active
    if is_verified is not None:
        user.is_verified = is_verified
    if is_superuser is not None:
        user.is_superuser = is_superuser
    await session.commit()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Current user: my groups
# ---------------------------------------------------------------------------


@router.get("/me/groups", tags=["users"])
async def get_my_groups(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return groups the current user belongs to."""
    stmt = (
        select(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user.id)
        .order_by(UserGroup.name)
    )
    result = await session.execute(stmt)
    groups = result.scalars().all()
    return [
        {"id": str(g.id), "name": g.name, "description": g.description}
        for g in groups
    ]
