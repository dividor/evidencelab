"""Group management routes — CRUD, membership, datasource access (admin only)."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import (
    GroupDatasourceAccess,
    User,
    UserGroup,
    UserGroupMember,
)
from ui.backend.auth.schemas import (
    GroupCreate,
    GroupDatasourceSet,
    GroupMemberAdd,
    GroupRead,
    GroupUpdate,
)
from ui.backend.auth.users import current_superuser

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _group_to_read(session: AsyncSession, group: UserGroup) -> GroupRead:
    """Convert a UserGroup ORM object to a GroupRead response."""
    ds_stmt = select(GroupDatasourceAccess.datasource_key).where(
        GroupDatasourceAccess.group_id == group.id
    )
    ds_result = await session.execute(ds_stmt)
    datasource_keys = list(ds_result.scalars().all())

    member_stmt = select(func.count()).where(UserGroupMember.group_id == group.id)
    member_result = await session.execute(member_stmt)
    member_count = member_result.scalar() or 0

    return GroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        created_at=group.created_at,
        datasource_keys=datasource_keys,
        member_count=member_count,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[GroupRead], tags=["groups"])
async def list_groups(
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List all groups (superuser only)."""
    result = await session.execute(select(UserGroup).order_by(UserGroup.name))
    groups = result.scalars().all()
    return [await _group_to_read(session, g) for g in groups]


@router.post("/", response_model=GroupRead, status_code=201, tags=["groups"])
async def create_group(
    body: GroupCreate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new group (superuser only)."""
    group = UserGroup(name=body.name, description=body.description)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return await _group_to_read(session, group)


# NOTE: concrete paths MUST come before the catch-all /{group_id} routes.


@router.get("/datasource-keys", tags=["groups"])
async def list_datasource_keys(
    admin: User = Depends(current_superuser),
):
    """List all configured datasource keys (superuser only).

    Used by the admin UI to populate the datasource access checkboxes
    when editing group permissions.
    """
    import pipeline.db as pipeline_db

    config = pipeline_db.load_datasources_config()
    return list(config.get("datasources", {}).keys())


@router.get("/{group_id}", response_model=GroupRead, tags=["groups"])
async def get_group(
    group_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Get a single group by ID (superuser only)."""
    result = await session.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalars().first()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return await _group_to_read(session, group)


@router.patch("/{group_id}", response_model=GroupRead, tags=["groups"])
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a group (superuser only)."""
    result = await session.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalars().first()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if body.name is not None:
        group.name = body.name
    if body.description is not None:
        group.description = body.description
    await session.commit()
    await session.refresh(group)
    return await _group_to_read(session, group)


@router.delete("/{group_id}", status_code=204, tags=["groups"])
async def delete_group(
    group_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a group (superuser only). Cannot delete the default group."""
    result = await session.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalars().first()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default group")
    await session.delete(group)
    await session.commit()


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


@router.get("/{group_id}/members", tags=["groups"])
async def list_group_members(
    group_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """List members of a group (superuser only)."""
    stmt = (
        select(User)
        .join(UserGroupMember, UserGroupMember.user_id == User.id)
        .where(UserGroupMember.group_id == group_id)
        .order_by(User.email)
    )
    result = await session.execute(stmt)
    users = result.unique().scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "is_active": u.is_active,
        }
        for u in users
    ]


@router.post("/{group_id}/members", status_code=201, tags=["groups"])
async def add_group_member(
    group_id: uuid.UUID,
    body: GroupMemberAdd,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Add a user to a group (superuser only)."""
    # Verify group exists
    g_result = await session.execute(select(UserGroup).where(UserGroup.id == group_id))
    if g_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Group not found")
    # Verify user exists
    u_result = await session.execute(select(User).where(User.id == body.user_id))
    if u_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Check if already a member
    existing = await session.execute(
        select(UserGroupMember).where(
            UserGroupMember.user_id == body.user_id,
            UserGroupMember.group_id == group_id,
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=409, detail="User already in group")
    membership = UserGroupMember(user_id=body.user_id, group_id=group_id)
    session.add(membership)
    await session.commit()
    return {"status": "added"}


@router.delete("/{group_id}/members/{user_id}", status_code=204, tags=["groups"])
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Remove a user from a group (superuser only)."""
    result = await session.execute(
        delete(UserGroupMember).where(
            UserGroupMember.user_id == user_id,
            UserGroupMember.group_id == group_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    await session.commit()


# ---------------------------------------------------------------------------
# Datasource access
# ---------------------------------------------------------------------------


@router.put("/{group_id}/datasources", response_model=GroupRead, tags=["groups"])
async def set_group_datasources(
    group_id: uuid.UUID,
    body: GroupDatasourceSet,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
):
    """Replace the set of datasource keys a group can access (superuser only)."""
    result = await session.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalars().first()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    # Remove existing grants
    await session.execute(
        delete(GroupDatasourceAccess).where(GroupDatasourceAccess.group_id == group_id)
    )
    # Insert new grants
    for key in body.datasource_keys:
        session.add(GroupDatasourceAccess(group_id=group_id, datasource_key=key))
    await session.commit()
    return await _group_to_read(session, group)
