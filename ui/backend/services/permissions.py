"""Permission checking logic for data-source access."""

import logging
import uuid
from typing import Optional, Set

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from pipeline.db import load_datasources_config
from ui.backend.auth.models import GroupDatasourceAccess, UserGroup, UserGroupMember

logger = logging.getLogger(__name__)


async def get_user_datasource_keys(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Set[str]:
    """Return the set of datasource keys the user is allowed to access.

    A user inherits access from every group they belong to (including the
    default group).  Each group has explicit datasource grants; there is no
    implicit "all access" shortcut.

    Args:
        session: Async database session.
        user_id: The user whose permissions to resolve.

    Returns:
        A set of datasource key strings.  An empty set means the user has
        no datasource access.
    """
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
        allowed_keys: Keys the user may access.  ``None`` means no
            filtering (anonymous / user module disabled).  An empty
            set means no access.

    Returns:
        Filtered datasources dict.
    """
    if allowed_keys is None:
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
        logger.warning(
            "No default group configured — new user %s will have no "
            "datasource access. Create a default group in the admin panel.",
            user_id,
        )
        return
    membership = UserGroupMember(user_id=user_id, group_id=default_group.id)
    session.add(membership)
    await session.commit()


async def ensure_data_source_access(session, user, data_source: str) -> None:
    """Refuse a signed-in user a data source none of their groups grants.

    Without this, a request naming no data source would reach the deployment's
    only one even for a user who has been given no access to it. Superusers
    and signed-out requests see every data source (see /config/datasources).
    """
    if getattr(user, "id", None) is None or user.is_superuser:
        return
    allowed = await get_user_datasource_keys(session, user.id)
    datasources = await run_in_threadpool(
        lambda: load_datasources_config().get("datasources", {})
    )
    permitted: Set[str] = set()
    for key, conf in filter_datasources(datasources, allowed).items():
        permitted.update({key, conf.get("data_subdir") or key})
    if data_source not in permitted:
        raise HTTPException(
            status_code=403,
            detail=(
                "You don't have access to this data source. Ask an administrator "
                "to add you to a group that has it."
            ),
        )
