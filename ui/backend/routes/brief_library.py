"""Brief library routes — templates and voice & tone profiles.

Both are owned by the user who created them and can be shared with a user
(by email) or a group (by name). Sharing is use-only: recipients can start a
brief from a shared template or write with a shared voice, and can make their
own copy, but only the owner can edit, delete or share the original. Owner
edits reach recipients, since a share points at the item rather than a copy.
"""

import copy
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import (
    BriefTemplate,
    BriefTemplateShare,
    User,
    VoiceProfile,
    VoiceProfileShare,
)
from ui.backend.auth.schemas import (
    BriefShareCreate,
    BriefShareTarget,
    BriefTemplateCreate,
    BriefTemplateHeading,
    BriefTemplateRead,
    BriefTemplateUpdate,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
)
from ui.backend.auth.users import current_active_user
from ui.backend.services.brief_sharing import (
    add_share,
    list_accessible,
    load_accessible,
    owner_names,
    remove_share,
    share_counts,
    share_targets,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATE_NOT_FOUND = "Template not found"
_PROFILE_NOT_FOUND = "Voice profile not found"
_UNKNOWN_VOICE = "Unknown voice & tone profile"
_COPY_PREFIX = "Copy of "
_NAME_MAX = 255

# Template fields that may be sent as null to clear them.
_CLEARABLE_TEMPLATE_FIELDS = ("prompt", "voice_profile_id", "target_words")


def _copy_name(name: str) -> str:
    """Name for a copy, kept within the column length."""
    return f"{_COPY_PREFIX}{name}"[:_NAME_MAX]


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------


async def _usable_template(
    session: AsyncSession, template_id: uuid.UUID, user: User
) -> tuple[BriefTemplate, bool]:
    """A template the user owns or that is shared with them, or 404."""
    template, can_edit = await load_accessible(
        session,
        BriefTemplate,
        BriefTemplateShare,
        BriefTemplateShare.template_id,
        template_id,
        user,
    )
    if template is None:
        raise HTTPException(status_code=404, detail=_TEMPLATE_NOT_FOUND)
    return template, can_edit


async def _owned_template(
    session: AsyncSession, template_id: uuid.UUID, user: User
) -> BriefTemplate:
    """A template the user owns, or 404 (also for one merely shared with them)."""
    template, can_edit = await _usable_template(session, template_id, user)
    if not can_edit:
        raise HTTPException(status_code=404, detail=_TEMPLATE_NOT_FOUND)
    return template


async def _usable_profile(
    session: AsyncSession, profile_id: uuid.UUID, user: User
) -> tuple[VoiceProfile, bool]:
    """A voice profile the user owns or that is shared with them, or 404."""
    profile, can_edit = await load_accessible(
        session,
        VoiceProfile,
        VoiceProfileShare,
        VoiceProfileShare.voice_profile_id,
        profile_id,
        user,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail=_PROFILE_NOT_FOUND)
    return profile, can_edit


async def _owned_profile(
    session: AsyncSession, profile_id: uuid.UUID, user: User
) -> VoiceProfile:
    """A voice profile the user owns, or 404 (also for one shared with them)."""
    profile, can_edit = await _usable_profile(session, profile_id, user)
    if not can_edit:
        raise HTTPException(status_code=404, detail=_PROFILE_NOT_FOUND)
    return profile


def _voice_ids(
    headings: list[dict[str, Any]], template_voice: uuid.UUID | None
) -> set[uuid.UUID]:
    """Every voice profile a template names, at template or heading level.

    ``headings`` is the stored JSON form, where ids are strings.
    """
    ids = {template_voice} if template_voice else set()
    ids.update(
        uuid.UUID(str(h["voice_profile_id"]))
        for h in headings
        if h.get("voice_profile_id")
    )
    return ids


def _headings_json(headings: list[BriefTemplateHeading]) -> list[dict[str, Any]]:
    """Headings as stored in the JSONB column (ids as strings)."""
    return [h.model_dump(mode="json") for h in headings]


async def _require_usable_voices(
    session: AsyncSession, user: User, voice_ids: set[uuid.UUID]
) -> None:
    """400 unless the user can use every voice profile named.

    Only newly named voices are checked, so a template that already names a
    voice its editor cannot see (a copy of a shared template, or a voice that
    was later unshared) can still be edited.
    """
    for voice_id in voice_ids:
        profile, _ = await load_accessible(
            session,
            VoiceProfile,
            VoiceProfileShare,
            VoiceProfileShare.voice_profile_id,
            voice_id,
            user,
        )
        if profile is None:
            raise HTTPException(status_code=400, detail=_UNKNOWN_VOICE)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


def _template_read(
    template: BriefTemplate, can_edit: bool, owner: str | None, share_count: int
) -> BriefTemplateRead:
    return BriefTemplateRead(
        id=template.id,
        name=template.name,
        description=template.description,
        headings=[BriefTemplateHeading.model_validate(h) for h in template.headings],
        with_text=template.with_text,
        prompt=template.prompt,
        voice_profile_id=template.voice_profile_id,
        target_words=template.target_words,
        use_count=template.use_count or 0,
        owner_name=None if can_edit else owner,
        can_edit=can_edit,
        share_count=share_count if can_edit else 0,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _profile_read(
    profile: VoiceProfile, can_edit: bool, owner: str | None, share_count: int
) -> VoiceProfileRead:
    return VoiceProfileRead(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        instructions=profile.instructions,
        owner_name=None if can_edit else owner,
        can_edit=can_edit,
        share_count=share_count if can_edit else 0,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _names_and_counts(
    session: AsyncSession,
    rows: list[tuple[Any, bool]],
    share_cls: Any,
    item_col: Any,
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, int]]:
    """Owner names for shared rows and share counts for owned rows."""
    names = await owner_names(session, (item.user_id for item, own in rows if not own))
    counts = await share_counts(
        session, share_cls, item_col, (item.id for item, own in rows if own)
    )
    return names, counts


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
    headings = _headings_json(body.headings)
    await _require_usable_voices(
        session, user, _voice_ids(headings, body.voice_profile_id)
    )
    template = BriefTemplate(
        user_id=user.id,
        name=body.name,
        description=body.description,
        headings=headings,
        with_text=body.with_text,
        prompt=body.prompt,
        voice_profile_id=body.voice_profile_id,
        target_words=body.target_words,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return _template_read(template, True, None, 0)


@router.get("/brief-templates/", tags=["brief-templates"])
async def list_templates(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """The user's own templates, then templates shared with them."""
    rows = await list_accessible(
        session,
        BriefTemplate,
        BriefTemplateShare,
        BriefTemplateShare.template_id,
        user,
        BriefTemplate.updated_at.desc(),
    )
    names, counts = await _names_and_counts(
        session, rows, BriefTemplateShare, BriefTemplateShare.template_id
    )
    return [
        _template_read(t, own, names.get(t.user_id), counts.get(t.id, 0))
        for t, own in rows
    ]


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
    template = await _owned_template(session, template_id, user)
    sent = body.model_fields_set
    headings = _headings_json(body.headings) if body.headings is not None else None
    new_voice = body.voice_profile_id if "voice_profile_id" in sent else None
    named = _voice_ids(headings or [], new_voice)
    already = _voice_ids(template.headings, template.voice_profile_id)
    await _require_usable_voices(session, user, named - already)
    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description
    if headings is not None:
        template.headings = headings
    if body.with_text is not None:
        template.with_text = body.with_text
    for field in _CLEARABLE_TEMPLATE_FIELDS:
        if field in sent:
            setattr(template, field, getattr(body, field))
    await session.commit()
    await session.refresh(template)
    counts = await share_counts(
        session, BriefTemplateShare, BriefTemplateShare.template_id, [template.id]
    )
    return _template_read(template, True, None, counts.get(template.id, 0))


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
    """Record one use of a template the user owns or was given, and return it."""
    template, can_edit = await _usable_template(session, template_id, user)
    template.use_count = (template.use_count or 0) + 1
    await session.commit()
    await session.refresh(template)
    names = await owner_names(session, [] if can_edit else [template.user_id])
    return _template_read(template, can_edit, names.get(template.user_id), 0)


@router.post(
    "/brief-templates/{template_id}/copy",
    response_model=BriefTemplateRead,
    tags=["brief-templates"],
)
async def copy_template(
    template_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Copy a template the user owns or was given into a new one they own."""
    source, _ = await _usable_template(session, template_id, user)
    template = BriefTemplate(
        user_id=user.id,
        name=_copy_name(source.name),
        description=source.description,
        headings=copy.deepcopy(source.headings),
        with_text=source.with_text,
        prompt=source.prompt,
        voice_profile_id=source.voice_profile_id,
        target_words=source.target_words,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return _template_read(template, True, None, 0)


@router.delete(
    "/brief-templates/{template_id}", status_code=204, tags=["brief-templates"]
)
async def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a template (owner only). Its shares go with it."""
    template = await _owned_template(session, template_id, user)
    await session.delete(template)
    await session.commit()


@router.get(
    "/brief-templates/{template_id}/shares",
    response_model=list[BriefShareTarget],
    tags=["brief-templates"],
)
async def list_template_shares(
    template_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """People and groups a template is shared with (owner only)."""
    template = await _owned_template(session, template_id, user)
    return await share_targets(
        session, BriefTemplateShare, BriefTemplateShare.template_id, template.id
    )


@router.post(
    "/brief-templates/{template_id}/shares",
    response_model=list[BriefShareTarget],
    tags=["brief-templates"],
)
async def add_template_share(
    template_id: uuid.UUID,
    body: BriefShareCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Share a template with a user (by email) or group (by name); owner only."""
    template = await _owned_template(session, template_id, user)
    await add_share(
        session,
        BriefTemplateShare,
        BriefTemplateShare.template_id,
        template.id,
        user,
        body.target,
        "template",
    )
    return await share_targets(
        session, BriefTemplateShare, BriefTemplateShare.template_id, template.id
    )


@router.delete(
    "/brief-templates/{template_id}/shares/{share_id}",
    status_code=204,
    tags=["brief-templates"],
)
async def remove_template_share(
    template_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Stop sharing a template with one user or group (owner only)."""
    template = await _owned_template(session, template_id, user)
    await remove_share(
        session,
        BriefTemplateShare,
        BriefTemplateShare.template_id,
        template.id,
        share_id,
    )


# ---------------------------------------------------------------------------
# Voice & tone profiles
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
    return _profile_read(profile, True, None, 0)


@router.get("/voice-profiles/", tags=["voice-profiles"])
async def list_voice_profiles(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """The user's own voice profiles, then profiles shared with them."""
    rows = await list_accessible(
        session,
        VoiceProfile,
        VoiceProfileShare,
        VoiceProfileShare.voice_profile_id,
        user,
        VoiceProfile.created_at.asc(),
    )
    names, counts = await _names_and_counts(
        session, rows, VoiceProfileShare, VoiceProfileShare.voice_profile_id
    )
    return [
        _profile_read(p, own, names.get(p.user_id), counts.get(p.id, 0))
        for p, own in rows
    ]


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
    profile = await _owned_profile(session, profile_id, user)
    if body.name is not None:
        profile.name = body.name
    if body.description is not None:
        profile.description = body.description
    if body.instructions is not None:
        profile.instructions = body.instructions
    await session.commit()
    await session.refresh(profile)
    counts = await share_counts(
        session, VoiceProfileShare, VoiceProfileShare.voice_profile_id, [profile.id]
    )
    return _profile_read(profile, True, None, counts.get(profile.id, 0))


@router.post(
    "/voice-profiles/{profile_id}/copy",
    response_model=VoiceProfileRead,
    tags=["voice-profiles"],
)
async def copy_voice_profile(
    profile_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Copy a voice profile the user owns or was given into a new one they own."""
    source, _ = await _usable_profile(session, profile_id, user)
    profile = VoiceProfile(
        user_id=user.id,
        name=_copy_name(source.name),
        description=source.description,
        instructions=source.instructions,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return _profile_read(profile, True, None, 0)


@router.delete("/voice-profiles/{profile_id}", status_code=204, tags=["voice-profiles"])
async def delete_voice_profile(
    profile_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a voice profile (owner only). Its shares go with it."""
    profile = await _owned_profile(session, profile_id, user)
    await session.delete(profile)
    await session.commit()


@router.get(
    "/voice-profiles/{profile_id}/shares",
    response_model=list[BriefShareTarget],
    tags=["voice-profiles"],
)
async def list_voice_profile_shares(
    profile_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """People and groups a voice profile is shared with (owner only)."""
    profile = await _owned_profile(session, profile_id, user)
    return await share_targets(
        session, VoiceProfileShare, VoiceProfileShare.voice_profile_id, profile.id
    )


@router.post(
    "/voice-profiles/{profile_id}/shares",
    response_model=list[BriefShareTarget],
    tags=["voice-profiles"],
)
async def add_voice_profile_share(
    profile_id: uuid.UUID,
    body: BriefShareCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Share a voice profile with a user (by email) or group (by name); owner only."""
    profile = await _owned_profile(session, profile_id, user)
    await add_share(
        session,
        VoiceProfileShare,
        VoiceProfileShare.voice_profile_id,
        profile.id,
        user,
        body.target,
        "voice & tone profile",
    )
    return await share_targets(
        session, VoiceProfileShare, VoiceProfileShare.voice_profile_id, profile.id
    )


@router.delete(
    "/voice-profiles/{profile_id}/shares/{share_id}",
    status_code=204,
    tags=["voice-profiles"],
)
async def remove_voice_profile_share(
    profile_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Stop sharing a voice profile with one user or group (owner only)."""
    profile = await _owned_profile(session, profile_id, user)
    await remove_share(
        session,
        VoiceProfileShare,
        VoiceProfileShare.voice_profile_id,
        profile.id,
        share_id,
    )
