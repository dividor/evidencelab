"""Permission checking logic for data-source access."""

import uuid
from typing import Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.models import GroupDatasourceAccess, UserGroup, UserGroupMember


async def get_user_datasource_keys(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Set[str]:
    """Return the set of datasource keys the user is allowed to access.

    A user inherits access from all groups they belong to.  Members of the
    default group (``is_default=True``) get access to *all* datasources,
    which is signalled by returning an empty set.

    Args:
        session: Async database session.
        user_id: The user whose permissions to resolve.

    Returns:
        A set of datasource key strings, or an empty set meaning "all".
    """
    # Check if user belongs to the default (all-access) group
    default_check = (
        select(UserGroup.id)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user_id, UserGroup.is_default.is_(True))
    )
    result = await session.execute(default_check)
    if result.scalars().first() is not None:
        return set()  # empty = all access

    # Collect explicit datasource grants from all groups
    stmt = (
        select(GroupDatasourceAccess.datasource_key)
        .join(
            UserGroupMember,
            UserGroupMember.group_id == GroupDatasourceAccess.group_id,
        )
        .where(UserGroupMember.user_id == user_id)
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


def filter_datasources(
    datasources: dict,
    allowed_keys: Optional[Set[str]],
) -> dict:
    """Filter a datasources dict to only include permitted entries.

    Args:
        datasources: Full datasources config dict (key → config).
        allowed_keys: Keys the user may access.  ``None`` or empty set
            means no filtering (user has access to all).

    Returns:
        Filtered datasources dict.
    """
    if allowed_keys is None or len(allowed_keys) == 0:
        return datasources
    return {k: v for k, v in datasources.items() if k in allowed_keys}


async def add_user_to_default_group(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Add a newly registered user to the default group.

    Args:
        session: Async database session.
        user_id: The new user's ID.
    """
    stmt = select(UserGroup).where(UserGroup.is_default.is_(True))
    result = await session.execute(stmt)
    default_group = result.scalars().first()
    if default_group is None:
        return
    membership = UserGroupMember(user_id=user_id, group_id=default_group.id)
    session.add(membership)
    await session.commit()
