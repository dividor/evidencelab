"""Per-group settings as one user sees them.

A group's ``search_settings`` JSONB holds the overrides an administrator set
on the Group Settings screen. A user may belong to several groups, so the
settings they get are merged here; both the ``/users/me/effective-settings``
route and the API features that apply a group setting server-side (the
brief Fact Checker's highlighted verdicts) read them through this module,
so every consumer gets the same answer.
"""

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.models import UserGroup, UserGroupMember

# Main feature tabs that a group can show/hide and relabel.
TAB_KEYS = ("search", "assistant", "brief", "heatmap")


def merge_tabs(tab_configs: Sequence[dict]) -> dict:
    """Union per-group tab visibility/labels.

    ``tab_configs`` is each group's ``search_settings['tabs']`` dict, ordered by
    group name ASC. A tab is **enabled if any group enables it**; its label comes
    from the first (lowest-priority-first) enabling group that sets a non-empty
    label, else ``None`` (the frontend then uses its default label).
    """
    result: dict = {}
    for tab in TAB_KEYS:
        enabled = False
        label = None
        for cfg in tab_configs:
            entry = cfg.get(tab) or {}
            if entry.get("enabled"):
                enabled = True
                if label is None:
                    candidate = (entry.get("label") or "").strip()
                    if candidate:
                        label = candidate
        result[tab] = {"enabled": enabled, "label": label}
    return result


def merge_group_settings(groups: Sequence) -> dict:
    """Merge search_settings from multiple groups (first non-null per key wins).

    Groups are expected to be ordered by name ASC so that the "Default" group
    has lowest priority (comes first alphabetically for most custom group names).

    The ``tabs`` key is special-cased: instead of first-non-null, it is unioned
    across groups (see :func:`merge_tabs`) so a feature tab shows if *any* group
    enables it. ``tabs`` is only present in the result when at least one group
    configured it.
    """
    merged: dict = {}
    tab_configs: list = []
    for group in groups:
        settings = group.search_settings
        if not settings:
            continue
        for key, value in settings.items():
            if key == "tabs":
                if isinstance(value, dict):
                    tab_configs.append(value)
                continue
            if key not in merged:
                merged[key] = value
    if tab_configs:
        merged["tabs"] = merge_tabs(tab_configs)
    return merged


async def user_groups(session: AsyncSession, user_id: uuid.UUID) -> Sequence[UserGroup]:
    """The groups a user belongs to, by name, so "Default" ranks lowest."""
    stmt = (
        select(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user_id)
        .order_by(UserGroup.name)
    )
    return (await session.execute(stmt)).scalars().all()


async def user_effective_settings(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """The merged settings of every group the user belongs to: only the
    overridden keys, an empty dict when nothing is overridden."""
    return merge_group_settings(await user_groups(session, user_id))
