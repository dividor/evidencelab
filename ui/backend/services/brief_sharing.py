"""Sharing for Brief Central: briefs, templates and voice & tone profiles.

Every shareable item has a share table whose rows grant one user (matched by
email) or every member of one group (matched by name) access to one item.
What that access allows is up to the item: a brief is viewer-only, a template
or voice profile is use-only. Only the owner can edit, delete or share.

The helpers here are generic over the share table so all three item types
resolve targets, check access and list recipients the same way.
"""

import uuid
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from ui.backend.auth.models import User, UserGroup, UserGroupMember
from ui.backend.auth.schemas import BriefShareTarget

SHARE_NOT_FOUND = "Share not found"


def owner_name(user: User) -> str:
    """Display name for an item's owner."""
    return user.full_name or user.email


async def user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """IDs of every group the user belongs to."""
    result = await session.execute(
        select(UserGroupMember.group_id).where(UserGroupMember.user_id == user_id)
    )
    return [row[0] for row in result.all()]


def shared_with(
    share_cls: Any, user_id: uuid.UUID, group_ids: list[uuid.UUID]
) -> ColumnElement[bool]:
    """SQL condition: a share row names this user or one of their groups."""
    condition: ColumnElement[bool] = share_cls.shared_user_id == user_id
    if group_ids:
        condition = or_(condition, share_cls.group_id.in_(group_ids))
    return condition


async def load_accessible(
    session: AsyncSession,
    model: Any,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
    user: User,
) -> tuple[Any, bool]:
    """Load an item the user owns or that is shared with them.

    Returns ``(item, can_edit)``; ``item`` is None when it does not exist or
    the user has no access, which callers must not tell apart.
    """
    item = await session.get(model, item_id)
    if item is None:
        return None, False
    if item.user_id == user.id:
        return item, True
    group_ids = await user_group_ids(session, user.id)
    result = await session.execute(
        select(share_cls.id).where(
            item_col == item_id, shared_with(share_cls, user.id, group_ids)
        )
    )
    if result.scalars().first() is None:
        return None, False
    return item, False


async def list_accessible(
    session: AsyncSession,
    model: Any,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    user: User,
    order_by: Any,
) -> list[tuple[Any, bool]]:
    """The user's own items, then items shared with them, as ``(item, can_edit)``."""
    owned = await session.execute(
        select(model).where(model.user_id == user.id).order_by(order_by)
    )
    group_ids = await user_group_ids(session, user.id)
    shared_ids = select(item_col).where(shared_with(share_cls, user.id, group_ids))
    shared = await session.execute(
        select(model)
        .where(model.id.in_(shared_ids), model.user_id != user.id)
        .order_by(order_by)
    )
    return [(item, True) for item in owned.scalars().all()] + [
        (item, False) for item in shared.scalars().all()
    ]


async def owner_names(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Display names for a set of owners, in one query."""
    ids = set(user_ids)
    if not ids:
        return {}
    result = await session.execute(select(User).where(User.id.in_(ids)))
    # unique(): User eager-loads collections (oauth accounts), which
    # SQLAlchemy requires be de-duplicated before iterating.
    return {u.id: owner_name(u) for u in result.scalars().unique().all()}


async def share_counts(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Number of share rows per item, in one query."""
    ids = list(item_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(item_col, func.count(share_cls.id))
        .where(item_col.in_(ids))
        .group_by(item_col)
    )
    return {row[0]: row[1] for row in result.all()}


async def resolve_share_target(
    session: AsyncSession, target: str
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolve a share target string to ``(user_id, group_id)``.

    An address containing "@" is matched against user emails; anything else is
    matched against group names. Unknown targets raise 404.
    """
    if "@" in target:
        result = await session.execute(
            select(User).where(func.lower(User.email) == target.lower())
        )
        matched_user = result.scalars().first()
        if not matched_user:
            raise HTTPException(
                status_code=404, detail="No user with that email address"
            )
        return matched_user.id, None
    result = await session.execute(
        select(UserGroup).where(func.lower(UserGroup.name) == target.lower())
    )
    group = result.scalars().first()
    if not group:
        raise HTTPException(status_code=404, detail="No group with that name")
    return None, group.id


async def share_targets(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
) -> list[BriefShareTarget]:
    """The people and groups an item is shared with, for the Share dialog."""
    result = await session.execute(select(share_cls).where(item_col == item_id))
    targets: list[BriefShareTarget] = []
    for share in result.scalars().all():
        target = await _share_target(session, share)
        if target is not None:
            targets.append(target)
    return targets


async def _share_target(session: AsyncSession, share: Any) -> BriefShareTarget | None:
    """One share row as a display target; None if its user or group is gone."""
    if share.shared_user_id:
        user_row = await session.get(User, share.shared_user_id)
        if user_row is None:
            return None
        return BriefShareTarget(
            id=share.id,
            name=user_row.full_name or user_row.email,
            kind=user_row.email,
            is_group=False,
        )
    group = await session.get(UserGroup, share.group_id)
    if group is None:
        return None
    return BriefShareTarget(
        id=share.id,
        name=group.name,
        kind=f"Group · {len(group.members)} members",
        is_group=True,
    )


ShareTarget = tuple[uuid.UUID | None, uuid.UUID | None]


async def ensure_share(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
    target: ShareTarget,
) -> bool:
    """Add a share row for ``(user_id, group_id)`` unless one exists.

    Returns True when a row was added. Does not commit.
    """
    shared_user_id, group_id = target
    existing = await session.execute(
        select(share_cls.id).where(
            item_col == item_id,
            share_cls.shared_user_id == shared_user_id,
            share_cls.group_id == group_id,
        )
    )
    if existing.scalars().first() is not None:
        return False
    session.add(
        share_cls(
            **{item_col.key: item_id},
            shared_user_id=shared_user_id,
            group_id=group_id,
        )
    )
    return True


async def add_share(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
    owner: User,
    target: str,
    item_label: str,
) -> ShareTarget:
    """Share an item with a user (by email) or a group (by name).

    Returns the ``(user_id, group_id)`` it was shared with. Raises 404 for an
    unknown target, 400 when the owner names themselves and 409 when the item
    is already shared with that target.
    """
    resolved = await resolve_share_target(session, target.strip())
    if resolved[0] == owner.id:
        raise HTTPException(
            status_code=400, detail=f"You already own this {item_label}"
        )
    if not await ensure_share(session, share_cls, item_col, item_id, resolved):
        raise HTTPException(status_code=409, detail="Already shared")
    await session.commit()
    return resolved


async def item_share_targets(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
) -> list[ShareTarget]:
    """Every ``(user_id, group_id)`` an item is shared with."""
    result = await session.execute(
        select(share_cls.shared_user_id, share_cls.group_id).where(item_col == item_id)
    )
    return [(row[0], row[1]) for row in result.all()]


async def remove_share(
    session: AsyncSession,
    share_cls: Any,
    item_col: InstrumentedAttribute,
    item_id: uuid.UUID,
    share_id: uuid.UUID,
) -> None:
    """Revoke one share of an item; 404 if that share is not on this item."""
    result = await session.execute(
        select(share_cls).where(share_cls.id == share_id, item_col == item_id)
    )
    share = result.scalars().first()
    if share is None:
        raise HTTPException(status_code=404, detail=SHARE_NOT_FOUND)
    await session.delete(share)
    await session.commit()
