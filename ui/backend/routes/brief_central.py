"""Brief Central routes — briefs, sharing, templates and voice profiles.

Briefs are user-owned. Sharing is viewer-only: a share row grants read access
to a single user (matched by email) or to every member of a group (matched by
group name). Templates and voice profiles are private to their owner.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import (
    Brief,
    BriefShare,
    BriefTemplate,
    User,
    UserGroup,
    UserGroupMember,
    VoiceProfile,
)
from ui.backend.auth.schemas import (
    BriefCreate,
    BriefListItem,
    BriefRead,
    BriefShareCreate,
    BriefShareTarget,
    BriefTemplateCreate,
    BriefTemplateRead,
    BriefTemplateUpdate,
    BriefUpdate,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
)
from ui.backend.auth.users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()

_BRIEF_NOT_FOUND = "Brief not found"
_TEMPLATE_NOT_FOUND = "Template not found"
_PROFILE_NOT_FOUND = "Voice profile not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner_name(user: User) -> str:
    """Display name for a brief owner."""
    return user.full_name or user.email


async def _user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """IDs of every group the user belongs to."""
    result = await session.execute(
        select(UserGroupMember.group_id).where(UserGroupMember.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def _get_owned_brief(
    session: AsyncSession, brief_id: uuid.UUID, user: User
) -> Brief:
    """Load a brief owned by *user* or raise 404."""
    result = await session.execute(
        select(Brief).where(Brief.id == brief_id, Brief.user_id == user.id)
    )
    brief = result.scalars().first()
    if not brief:
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    return brief


async def _get_viewable_brief(
    session: AsyncSession, brief_id: uuid.UUID, user: User
) -> tuple[Brief, bool]:
    """Load a brief the user owns or was granted view access to.

    Returns (brief, can_edit). Raises 404 when the brief does not exist or the
    user has no access — the two cases are indistinguishable on purpose.
    """
    result = await session.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalars().first()
    if not brief:
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    if brief.user_id == user.id:
        return brief, True
    group_ids = await _user_group_ids(session, user.id)
    condition = BriefShare.shared_user_id == user.id
    if group_ids:
        condition = condition | BriefShare.group_id.in_(group_ids)
    share_rows = await session.execute(
        select(BriefShare.id).where(BriefShare.brief_id == brief_id, condition)
    )
    if not share_rows.scalars().first():
        raise HTTPException(status_code=404, detail=_BRIEF_NOT_FOUND)
    return brief, False


async def _share_targets(
    session: AsyncSession, brief_id: uuid.UUID
) -> list[BriefShareTarget]:
    """Resolve share rows to display targets."""
    result = await session.execute(
        select(BriefShare).where(BriefShare.brief_id == brief_id)
    )
    targets: list[BriefShareTarget] = []
    for share in result.scalars().all():
        if share.shared_user_id:
            user_row = await session.get(User, share.shared_user_id)
            if user_row:
                targets.append(
                    BriefShareTarget(
                        id=share.id,
                        name=user_row.full_name or user_row.email,
                        kind=user_row.email,
                        is_group=False,
                    )
                )
        elif share.group_id:
            group = await session.get(UserGroup, share.group_id)
            if group:
                member_count = len(group.members)
                targets.append(
                    BriefShareTarget(
                        id=share.id,
                        name=group.name,
                        kind=f"Group · {member_count} members",
                        is_group=True,
                    )
                )
    return targets


async def _to_brief_read(
    session: AsyncSession, brief: Brief, can_edit: bool
) -> BriefRead:
    """Build the full read model, including owner name and share targets."""
    owner = await session.get(User, brief.user_id)
    return BriefRead(
        id=brief.id,
        user_id=brief.user_id,
        title=brief.title,
        query=brief.query,
        data_source=brief.data_source,
        voice_profile_id=brief.voice_profile_id,
        content=brief.content,
        owner_name=_owner_name(owner) if owner else None,
        can_edit=can_edit,
        shared_with=await _share_targets(session, brief.id) if can_edit else [],
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


def _to_list_item(
    brief: Brief, owner_name: str | None, share_count: int
) -> BriefListItem:
    """Compact card model for list views."""
    content = brief.content or {}
    sections = content.get("sections") or []
    return BriefListItem(
        id=brief.id,
        title=brief.title,
        query=brief.query,
        data_source=brief.data_source,
        voice_profile_id=brief.voice_profile_id,
        section_count=len(sections),
        source_count=content.get("sourceCount") or 0,
        owner_name=owner_name,
        share_count=share_count,
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


@router.post("/briefs/", response_model=BriefRead, tags=["briefs"])
async def create_brief(
    body: BriefCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Save a new brief."""
    brief = Brief(
        user_id=user.id,
        title=body.title,
        query=body.query,
        data_source=body.data_source,
        voice_profile_id=body.voice_profile_id,
        content=body.content,
    )
    session.add(brief)
    await session.commit()
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.get("/briefs/", tags=["briefs"])
async def list_briefs(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the current user's briefs (compact, newest first)."""
    result = await session.execute(
        select(Brief).where(Brief.user_id == user.id).order_by(Brief.updated_at.desc())
    )
    briefs = result.scalars().all()
    counts = await session.execute(
        select(BriefShare.brief_id, func.count(BriefShare.id))
        .where(BriefShare.brief_id.in_([b.id for b in briefs]))
        .group_by(BriefShare.brief_id)
    )
    count_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in counts.all()}
    return [_to_list_item(b, None, count_map.get(b.id, 0)) for b in briefs]


@router.get("/briefs/shared", tags=["briefs"])
async def list_shared_briefs(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List briefs shared with the current user (directly or via a group)."""
    group_ids = await _user_group_ids(session, user.id)
    condition = BriefShare.shared_user_id == user.id
    if group_ids:
        condition = condition | BriefShare.group_id.in_(group_ids)
    result = await session.execute(
        select(Brief)
        .join(BriefShare, BriefShare.brief_id == Brief.id)
        .where(condition, Brief.user_id != user.id)
        .order_by(Brief.updated_at.desc())
        .distinct()
    )
    items = []
    for brief in result.scalars().all():
        owner = await session.get(User, brief.user_id)
        items.append(_to_list_item(brief, _owner_name(owner) if owner else None, 0))
    return items


@router.get("/briefs/{brief_id}", response_model=BriefRead, tags=["briefs"])
async def get_brief(
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Load a single brief the user owns or can view."""
    brief, can_edit = await _get_viewable_brief(session, brief_id, user)
    return await _to_brief_read(session, brief, can_edit)


@router.put("/briefs/{brief_id}", response_model=BriefRead, tags=["briefs"])
async def update_brief(
    brief_id: uuid.UUID,
    body: BriefUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a brief (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    if body.title is not None:
        brief.title = body.title
    if body.query is not None:
        brief.query = body.query
    if body.voice_profile_id is not None:
        brief.voice_profile_id = body.voice_profile_id
    if body.content is not None:
        brief.content = body.content
    await session.commit()
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.delete("/briefs/{brief_id}", status_code=204, tags=["briefs"])
async def delete_brief(
    brief_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a brief (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    await session.delete(brief)
    await session.commit()


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------


async def _resolve_share_target(
    session: AsyncSession, target: str
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolve a share target string to (user_id, group_id).

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


@router.post("/briefs/{brief_id}/shares", response_model=BriefRead, tags=["briefs"])
async def add_brief_share(
    brief_id: uuid.UUID,
    body: BriefShareCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Grant viewer access to a user (by email) or group (by name)."""
    brief = await _get_owned_brief(session, brief_id, user)
    shared_user_id, group_id = await _resolve_share_target(session, body.target.strip())
    if shared_user_id == user.id:
        raise HTTPException(status_code=400, detail="You already own this brief")
    existing = await session.execute(
        select(BriefShare).where(
            BriefShare.brief_id == brief.id,
            BriefShare.shared_user_id == shared_user_id,
            BriefShare.group_id == group_id,
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Already shared")
    session.add(
        BriefShare(brief_id=brief.id, shared_user_id=shared_user_id, group_id=group_id)
    )
    await session.commit()
    await session.refresh(brief)
    return await _to_brief_read(session, brief, can_edit=True)


@router.delete("/briefs/{brief_id}/shares/{share_id}", status_code=204, tags=["briefs"])
async def remove_brief_share(
    brief_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke a share (owner only)."""
    brief = await _get_owned_brief(session, brief_id, user)
    result = await session.execute(
        select(BriefShare).where(
            BriefShare.id == share_id, BriefShare.brief_id == brief.id
        )
    )
    share = result.scalars().first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    await session.delete(share)
    await session.commit()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.post(
    "/brief-templates/", response_model=BriefTemplateRead, tags=["brief-templates"]
)
async def create_template(
    body: BriefTemplateCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a brief template."""
    template = BriefTemplate(
        user_id=user.id,
        name=body.name,
        description=body.description,
        headings=[h.model_dump() for h in body.headings],
        with_text=body.with_text,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return BriefTemplateRead.model_validate(template)


@router.get("/brief-templates/", tags=["brief-templates"])
async def list_templates(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the current user's templates."""
    result = await session.execute(
        select(BriefTemplate)
        .where(BriefTemplate.user_id == user.id)
        .order_by(BriefTemplate.updated_at.desc())
    )
    return [BriefTemplateRead.model_validate(t) for t in result.scalars().all()]


async def _get_owned_template(
    session: AsyncSession, template_id: uuid.UUID, user: User
) -> BriefTemplate:
    """Load a template owned by *user* or raise 404."""
    result = await session.execute(
        select(BriefTemplate).where(
            BriefTemplate.id == template_id, BriefTemplate.user_id == user.id
        )
    )
    template = result.scalars().first()
    if not template:
        raise HTTPException(status_code=404, detail=_TEMPLATE_NOT_FOUND)
    return template


@router.put(
    "/brief-templates/{template_id}",
    response_model=BriefTemplateRead,
    tags=["brief-templates"],
)
async def update_template(
    template_id: uuid.UUID,
    body: BriefTemplateUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a template (owner only)."""
    template = await _get_owned_template(session, template_id, user)
    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description
    if body.headings is not None:
        template.headings = [h.model_dump() for h in body.headings]
    if body.with_text is not None:
        template.with_text = body.with_text
    await session.commit()
    await session.refresh(template)
    return BriefTemplateRead.model_validate(template)


@router.post(
    "/brief-templates/{template_id}/use",
    response_model=BriefTemplateRead,
    tags=["brief-templates"],
)
async def use_template(
    template_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Record one use of a template and return it."""
    template = await _get_owned_template(session, template_id, user)
    template.use_count = (template.use_count or 0) + 1
    await session.commit()
    await session.refresh(template)
    return BriefTemplateRead.model_validate(template)


@router.delete(
    "/brief-templates/{template_id}", status_code=204, tags=["brief-templates"]
)
async def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a template (owner only)."""
    template = await _get_owned_template(session, template_id, user)
    await session.delete(template)
    await session.commit()


# ---------------------------------------------------------------------------
# Voice profiles
# ---------------------------------------------------------------------------


@router.post(
    "/voice-profiles/", response_model=VoiceProfileRead, tags=["voice-profiles"]
)
async def create_voice_profile(
    body: VoiceProfileCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a voice & tone profile."""
    profile = VoiceProfile(
        user_id=user.id,
        name=body.name,
        description=body.description,
        instructions=body.instructions,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return VoiceProfileRead.model_validate(profile)


@router.get("/voice-profiles/", tags=["voice-profiles"])
async def list_voice_profiles(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the current user's voice profiles."""
    result = await session.execute(
        select(VoiceProfile)
        .where(VoiceProfile.user_id == user.id)
        .order_by(VoiceProfile.created_at.asc())
    )
    return [VoiceProfileRead.model_validate(p) for p in result.scalars().all()]


async def _get_owned_profile(
    session: AsyncSession, profile_id: uuid.UUID, user: User
) -> VoiceProfile:
    """Load a voice profile owned by *user* or raise 404."""
    result = await session.execute(
        select(VoiceProfile).where(
            VoiceProfile.id == profile_id, VoiceProfile.user_id == user.id
        )
    )
    profile = result.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail=_PROFILE_NOT_FOUND)
    return profile


@router.put(
    "/voice-profiles/{profile_id}",
    response_model=VoiceProfileRead,
    tags=["voice-profiles"],
)
async def update_voice_profile(
    profile_id: uuid.UUID,
    body: VoiceProfileUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a voice profile (owner only)."""
    profile = await _get_owned_profile(session, profile_id, user)
    if body.name is not None:
        profile.name = body.name
    if body.description is not None:
        profile.description = body.description
    if body.instructions is not None:
        profile.instructions = body.instructions
    await session.commit()
    await session.refresh(profile)
    return VoiceProfileRead.model_validate(profile)


@router.delete("/voice-profiles/{profile_id}", status_code=204, tags=["voice-profiles"])
async def delete_voice_profile(
    profile_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a voice profile (owner only)."""
    profile = await _get_owned_profile(session, profile_id, user)
    await session.delete(profile)
    await session.commit()
