"""Sharing templates and voice & tone profiles, against the real database.

Who can see, use, copy, edit and share an item is decided by SQL (owner, a
share naming the user, or a share naming one of their groups), so these tests
call the route handlers with a real async session on the stack's Postgres.
Each test runs inside a transaction that is rolled back afterwards: the
handlers' commits become savepoints, and nothing is left in the database.

Requires the Docker stack (Postgres with migrations applied).
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL
from ui.backend.auth.models import (
    Brief,
    BriefTemplate,
    BriefTemplateShare,
    User,
    UserGroup,
    UserGroupMember,
)
from ui.backend.auth.schemas import (
    BriefShareCreate,
    BriefTemplateCreate,
    BriefTemplateHeading,
    BriefTemplateUpdate,
    VoiceProfileCreate,
    VoiceProfileUpdate,
)
from ui.backend.routes import brief_central, brief_library

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

HASH = "not-a-real-password-hash"  # pragma: allowlist secret
# FastAPI passes the request; these tests call the handlers directly.
NO_REQUEST = SimpleNamespace(client=None)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


async def _user(db: AsyncSession, label: str) -> User:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.org",
        hashed_password=HASH,
        first_name=label.capitalize(),
    )
    db.add(user)
    await db.flush()
    return user


async def _group(db: AsyncSession, *members: User) -> UserGroup:
    group = UserGroup(name=f"team-{uuid.uuid4().hex[:8]}")
    db.add(group)
    await db.flush()
    for member in members:
        db.add(UserGroupMember(user_id=member.id, group_id=group.id))
    await db.flush()
    return group


def _heading(title: str, **extra) -> BriefTemplateHeading:
    return BriefTemplateHeading(title=title, **extra)


async def _template(db: AsyncSession, owner: User, **extra):
    body = BriefTemplateCreate(
        name="Evaluation synthesis",
        headings=[
            _heading("Context"),
            _heading("Findings", prompt="Lead with outcomes"),
        ],
        **extra,
    )
    return await brief_library.create_template(body=body, user=owner, session=db)


async def _voice(db: AsyncSession, owner: User, name: str = "Donor memo"):
    body = VoiceProfileCreate(name=name, instructions="Plain English, findings first.")
    return await brief_library.create_voice_profile(body=body, user=owner, session=db)


async def _share_template(db, owner, template_id, target):
    return await brief_library.add_template_share(
        template_id=template_id,
        body=BriefShareCreate(target=target),
        user=owner,
        session=db,
    )


async def _share_voice(db, owner, profile_id, target):
    return await brief_library.add_voice_profile_share(
        profile_id=profile_id,
        body=BriefShareCreate(target=target),
        user=owner,
        session=db,
    )


async def _expect_404(coro):
    with pytest.raises(HTTPException) as err:
        await coro
    assert err.value.status_code == 404


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


async def test_template_shared_with_user_is_listed_use_only(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)

    targets = await _share_template(session, owner, template.id, reader.email)

    assert [t.kind for t in targets] == [reader.email]
    listed = await brief_library.list_templates(user=reader, session=session)
    assert [(t.id, t.can_edit, t.owner_name) for t in listed] == [
        (template.id, False, "Owner")
    ]
    mine = await brief_library.list_templates(user=owner, session=session)
    assert [(t.id, t.can_edit, t.share_count) for t in mine] == [(template.id, True, 1)]


async def test_template_shared_with_group_reaches_members_only(session):
    owner = await _user(session, "owner")
    member, outsider = await _user(session, "member"), await _user(session, "outsider")
    group = await _group(session, member)
    template = await _template(session, owner)

    await _share_template(session, owner, template.id, group.name)

    member_ids = [
        t.id for t in await brief_library.list_templates(user=member, session=session)
    ]
    outsider_ids = [
        t.id for t in await brief_library.list_templates(user=outsider, session=session)
    ]
    assert member_ids == [template.id]
    assert outsider_ids == []
    await _expect_404(
        brief_library.use_template(
            template_id=template.id, user=outsider, session=session
        )
    )


async def test_recipient_can_use_and_copy_but_not_change_the_original(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    await _share_template(session, owner, template.id, reader.email)

    used = await brief_library.use_template(
        template_id=template.id, user=reader, session=session
    )
    copied = await brief_library.copy_template(
        template_id=template.id, user=reader, session=session
    )

    assert (used.use_count, used.can_edit) == (1, False)
    assert copied.id != template.id
    assert (copied.name, copied.can_edit) == ("Copy of Evaluation synthesis", True)
    assert copied.headings[1].prompt == "Lead with outcomes"
    edit = BriefTemplateUpdate(name="Hijacked")
    await _expect_404(
        brief_library.update_template(
            template_id=template.id, body=edit, user=reader, session=session
        )
    )
    await _expect_404(
        brief_library.delete_template(
            template_id=template.id, user=reader, session=session
        )
    )
    await _expect_404(_share_template(session, reader, template.id, owner.email))
    await _expect_404(
        brief_library.list_template_shares(
            template_id=template.id, user=reader, session=session
        )
    )


async def test_owner_edits_reach_recipients(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    await _share_template(session, owner, template.id, reader.email)

    await brief_library.update_template(
        template_id=template.id,
        body=BriefTemplateUpdate(prompt="Cover 2020 onward"),
        user=owner,
        session=session,
    )

    seen = await brief_library.list_templates(user=reader, session=session)
    assert seen[0].prompt == "Cover 2020 onward"


async def test_revoking_a_share_removes_access(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    targets = await _share_template(session, owner, template.id, reader.email)

    await brief_library.remove_template_share(
        template_id=template.id, share_id=targets[0].id, user=owner, session=session
    )

    assert await brief_library.list_templates(user=reader, session=session) == []
    await _expect_404(
        brief_library.copy_template(
            template_id=template.id, user=reader, session=session
        )
    )


async def test_prompts_voices_and_lengths_round_trip_and_clear(session):
    owner = await _user(session, "owner")
    voice = await _voice(session, owner)
    body = BriefTemplateCreate(
        name="Board memo",
        headings=[
            _heading("Summary", prompt="Three bullets", target_words=150),
            _heading("Detail", sub=True, voice_profile_id=voice.id),
        ],
        prompt="Focus on East Africa",
        voice_profile_id=voice.id,
        target_words=350,
    )
    created = await brief_library.create_template(
        body=body, user=owner, session=session
    )

    assert (created.prompt, created.voice_profile_id, created.target_words) == (
        "Focus on East Africa",
        voice.id,
        350,
    )
    assert created.headings[0].prompt == "Three bullets"
    assert created.headings[0].target_words == 150
    assert created.headings[1].voice_profile_id == voice.id

    cleared = await brief_library.update_template(
        template_id=created.id,
        body=BriefTemplateUpdate(prompt=None, voice_profile_id=None, target_words=None),
        user=owner,
        session=session,
    )
    untouched = await brief_library.update_template(
        template_id=created.id,
        body=BriefTemplateUpdate(name="Board memo v2"),
        user=owner,
        session=session,
    )
    assert (cleared.prompt, cleared.voice_profile_id, cleared.target_words) == (
        None,
        None,
        None,
    )
    assert untouched.headings[0].prompt == "Three bullets"


async def test_template_may_only_name_voices_the_author_can_use(session):
    owner, other = await _user(session, "owner"), await _user(session, "other")
    private_voice = await _voice(session, other, "Their private voice")
    shared_voice = await _voice(session, other, "Their shared voice")
    await _share_voice(session, other, shared_voice.id, owner.email)

    with pytest.raises(HTTPException) as err:
        await _template(session, owner, voice_profile_id=private_voice.id)
    assert err.value.status_code == 400

    heading_voice = BriefTemplateCreate(
        name="Uses a shared voice",
        headings=[_heading("Findings", voice_profile_id=shared_voice.id)],
    )
    created = await brief_library.create_template(
        body=heading_voice, user=owner, session=session
    )
    assert created.headings[0].voice_profile_id == shared_voice.id


async def test_copy_keeps_a_voice_the_copier_cannot_see_and_stays_editable(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    # A third person's voice, shared with the owner only: sharing the template
    # cannot pass it on, so the reader never sees it.
    third = await _user(session, "third")
    voice = await _voice(session, third, "Third person's voice")
    await _share_voice(session, third, voice.id, owner.email)
    template = await _template(session, owner, voice_profile_id=voice.id)
    await _share_template(session, owner, template.id, reader.email)

    copied = await brief_library.copy_template(
        template_id=template.id, user=reader, session=session
    )
    renamed = await brief_library.update_template(
        template_id=copied.id,
        body=BriefTemplateUpdate(name="Mine now"),
        user=reader,
        session=session,
    )

    assert renamed.voice_profile_id == voice.id
    voices = await brief_library.list_voice_profiles(user=reader, session=session)
    assert voice.id not in [v.id for v in voices]


async def _voice_ids_of(session, user):
    voices = await brief_library.list_voice_profiles(user=user, session=session)
    return {v.id for v in voices if not v.can_edit}


async def test_sharing_a_template_shares_the_owners_voices_it_uses(session):
    owner, member = await _user(session, "owner"), await _user(session, "member")
    group = await _group(session, member)
    brief_voice = await _voice(session, owner, "Board register")
    section_voice = await _voice(session, owner, "Field register")
    unused_voice = await _voice(session, owner, "Not in the template")
    body = BriefTemplateCreate(
        name="Team template",
        headings=[
            _heading("Summary"),
            _heading("Detail", voice_profile_id=section_voice.id),
        ],
        voice_profile_id=brief_voice.id,
    )
    template = await brief_library.create_template(
        body=body, user=owner, session=session
    )

    await _share_template(session, owner, template.id, group.name)

    assert await _voice_ids_of(session, member) == {brief_voice.id, section_voice.id}
    assert unused_voice.id not in await _voice_ids_of(session, member)


async def test_voices_owned_by_someone_else_are_not_passed_on(session):
    owner, reader, third = (
        await _user(session, "owner"),
        await _user(session, "reader"),
        await _user(session, "third"),
    )
    theirs = await _voice(session, third, "Third person's voice")
    await _share_voice(session, third, theirs.id, owner.email)
    template = await _template(session, owner, voice_profile_id=theirs.id)

    await _share_template(session, owner, template.id, reader.email)

    assert await _voice_ids_of(session, reader) == set()


async def test_a_voice_added_to_a_shared_template_reaches_its_recipients(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    await _share_template(session, owner, template.id, reader.email)
    voice = await _voice(session, owner)

    await brief_library.update_template(
        template_id=template.id,
        body=BriefTemplateUpdate(voice_profile_id=voice.id),
        user=owner,
        session=session,
    )

    assert await _voice_ids_of(session, reader) == {voice.id}


async def test_a_voice_already_shared_is_not_shared_twice(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    voice = await _voice(session, owner)
    await _share_voice(session, owner, voice.id, reader.email)
    template = await _template(session, owner, voice_profile_id=voice.id)

    await _share_template(session, owner, template.id, reader.email)

    targets = await brief_library.list_voice_profile_shares(
        profile_id=voice.id, user=owner, session=session
    )
    assert [t.kind for t in targets] == [reader.email]


async def test_stopping_a_template_share_leaves_its_voices_shared(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    voice = await _voice(session, owner)
    template = await _template(session, owner, voice_profile_id=voice.id)
    targets = await _share_template(session, owner, template.id, reader.email)

    await brief_library.remove_template_share(
        template_id=template.id, share_id=targets[0].id, user=owner, session=session
    )

    assert await brief_library.list_templates(user=reader, session=session) == []
    assert await _voice_ids_of(session, reader) == {voice.id}


async def test_deleting_a_voice_clears_it_from_templates(session):
    owner = await _user(session, "owner")
    voice = await _voice(session, owner)
    template = await _template(session, owner, voice_profile_id=voice.id)

    await brief_library.delete_voice_profile(
        profile_id=voice.id, user=owner, session=session
    )

    row = await session.get(BriefTemplate, template.id)
    await session.refresh(row)
    assert row.voice_profile_id is None


async def test_sharing_rules(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    await _share_template(session, owner, template.id, reader.email)

    for target, status in [
        (owner.email, 400),
        (reader.email, 409),
        ("nobody@x.org", 404),
    ]:
        with pytest.raises(HTTPException) as err:
            await _share_template(session, owner, template.id, target)
        assert err.value.status_code == status


async def test_a_share_names_exactly_one_target(session):
    owner = await _user(session, "owner")
    group = await _group(session)
    template = await _template(session, owner)

    for user_id, group_id in [(None, None), (owner.id, group.id)]:
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    BriefTemplateShare(
                        template_id=template.id,
                        shared_user_id=user_id,
                        group_id=group_id,
                    )
                )
                await session.flush()


async def test_deleting_a_template_removes_its_shares(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    template = await _template(session, owner)
    await _share_template(session, owner, template.id, reader.email)

    await brief_library.delete_template(
        template_id=template.id, user=owner, session=session
    )

    rows = await session.execute(
        select(BriefTemplateShare).where(BriefTemplateShare.template_id == template.id)
    )
    assert rows.scalars().all() == []


# ---------------------------------------------------------------------------
# Voice & tone profiles
# ---------------------------------------------------------------------------


async def test_voice_shared_with_group_is_usable_by_members(session):
    owner, member = await _user(session, "owner"), await _user(session, "member")
    group = await _group(session, member)
    voice = await _voice(session, owner)

    await _share_voice(session, owner, voice.id, group.name)

    seen = await brief_library.list_voice_profiles(user=member, session=session)
    assert [(v.id, v.can_edit, v.instructions) for v in seen] == [
        (voice.id, False, "Plain English, findings first.")
    ]
    copied = await brief_library.copy_voice_profile(
        profile_id=voice.id, user=member, session=session
    )
    assert (copied.name, copied.can_edit) == ("Copy of Donor memo", True)
    await _expect_404(
        brief_library.update_voice_profile(
            profile_id=voice.id,
            body=VoiceProfileUpdate(name="Changed"),
            user=member,
            session=session,
        )
    )
    await _expect_404(
        brief_library.delete_voice_profile(
            profile_id=voice.id, user=member, session=session
        )
    )


async def test_revoking_a_voice_share_removes_it(session):
    owner, reader = await _user(session, "owner"), await _user(session, "reader")
    voice = await _voice(session, owner)
    targets = await _share_voice(session, owner, voice.id, reader.email)

    await brief_library.remove_voice_profile_share(
        profile_id=voice.id, share_id=targets[0].id, user=owner, session=session
    )

    assert await brief_library.list_voice_profiles(user=reader, session=session) == []
    owned = await brief_library.list_voice_profiles(user=owner, session=session)
    assert (owned[0].share_count, owned[0].can_edit) == (0, True)


# ---------------------------------------------------------------------------
# Briefs: sharing moved onto the shared helpers
# ---------------------------------------------------------------------------


async def test_brief_shared_with_a_group_is_viewable_by_members(session):
    owner, member = await _user(session, "owner"), await _user(session, "member")
    outsider = await _user(session, "outsider")
    group = await _group(session, member)
    brief = Brief(user_id=owner.id, title="Cash", content={"sections": []})
    session.add(brief)
    await session.flush()

    shared = await brief_central.add_brief_share(
        brief_id=brief.id,
        body=BriefShareCreate(target=group.name),
        user=owner,
        session=session,
    )

    assert [t.is_group for t in shared.shared_with] == [True]
    viewed = await brief_central.get_brief(
        brief_id=brief.id, request=NO_REQUEST, user=member, session=session
    )
    assert (viewed.can_edit, viewed.owner_name) == (False, "Owner")
    listed = await brief_central.list_shared_briefs(user=member, session=session)
    assert [b.id for b in listed] == [brief.id]
    await _expect_404(
        brief_central.get_brief(
            brief_id=brief.id, request=NO_REQUEST, user=outsider, session=session
        )
    )
    await brief_central.remove_brief_share(
        brief_id=brief.id,
        share_id=shared.shared_with[0].id,
        user=owner,
        session=session,
    )
    await _expect_404(
        brief_central.get_brief(
            brief_id=brief.id, request=NO_REQUEST, user=member, session=session
        )
    )
