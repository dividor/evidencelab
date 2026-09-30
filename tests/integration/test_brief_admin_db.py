"""Administrator access to every brief, against the real database.

Superusers can list every brief with its owner, open any brief read-only and
copy any brief into their own; everyone else keeps their existing access.
Opening or copying a brief an administrator neither owns nor was sent is
recorded in the audit log. Each test runs in a rolled-back transaction; audit
writes (which use their own session) are captured instead of stored.

Requires the Docker stack (Postgres with migrations applied).
"""

import inspect
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ui.backend.auth.db import DATABASE_URL
from ui.backend.auth.models import Brief, BriefShare, User
from ui.backend.auth.users import current_superuser
from ui.backend.routes import brief_central

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

HASH = "not-a-real-password-hash"  # pragma: allowlist secret
REQUEST = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
def audit(monkeypatch):
    events = []

    async def capture(event_type, **kwargs):
        events.append((event_type, kwargs))

    monkeypatch.setattr(brief_central, "write_audit_event", capture)
    return events


async def _user(db, label, superuser=False):
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.org",
        hashed_password=HASH,
        first_name=label.capitalize(),
        is_superuser=superuser,
    )
    db.add(user)
    await db.flush()
    return user


async def _brief(db, owner, title):
    brief = Brief(
        user_id=owner.id,
        title=title,
        query=title,
        data_source="wfp",
        content={
            "title": title,
            "activityId": "act-original",
            "sections": [{"id": "s1", "title": "Findings", "content": "Text [1]."}],
        },
    )
    db.add(brief)
    await db.flush()
    return brief


async def _expect_404(coro):
    with pytest.raises(HTTPException) as err:
        await coro
    assert err.value.status_code == 404


def test_the_all_briefs_list_requires_a_superuser():
    param = inspect.signature(brief_central.list_all_briefs).parameters["user"]
    assert param.default.dependency is current_superuser


async def test_admin_lists_every_brief_with_its_owner(session):
    admin = await _user(session, "admin", superuser=True)
    alice, bob = await _user(session, "alice"), await _user(session, "bob")
    a = await _brief(session, alice, "Alice brief")
    b = await _brief(session, bob, "Bob brief")

    listed = await brief_central.list_all_briefs(user=admin, session=session)

    mine = {item.id: item for item in listed if item.id in (a.id, b.id)}
    assert (mine[a.id].owner_name, mine[a.id].owner_email) == ("Alice", alice.email)
    assert (mine[b.id].owner_name, mine[b.id].owner_email) == ("Bob", bob.email)


async def test_admin_opens_any_brief_read_only_and_it_is_audited(session, audit):
    admin = await _user(session, "admin", superuser=True)
    alice = await _user(session, "alice")
    brief = await _brief(session, alice, "Alice brief")

    read = await brief_central.get_brief(
        brief_id=brief.id, request=REQUEST, user=admin, session=session
    )

    assert (read.can_edit, read.owner_name, read.shared_with) == (False, "Alice", [])
    assert [e for e, _ in audit] == [brief_central.EVENT_BRIEF_ADMIN_VIEWED]
    details = audit[0][1]
    assert details["user_email"] == admin.email
    assert details["ip_address"] == "203.0.113.7"
    assert details["details"]["brief_id"] == str(brief.id)
    assert details["details"]["owner_id"] == str(alice.id)


async def test_admin_cannot_change_someone_elses_brief(session):
    admin = await _user(session, "admin", superuser=True)
    alice = await _user(session, "alice")
    brief = await _brief(session, alice, "Alice brief")
    await _expect_404(
        brief_central.delete_brief(brief_id=brief.id, user=admin, session=session)
    )


async def test_admins_own_and_shared_briefs_are_not_audited(session, audit):
    admin = await _user(session, "admin", superuser=True)
    alice = await _user(session, "alice")
    own = await _brief(session, admin, "Admin brief")
    shared = await _brief(session, alice, "Shared with admin")
    session.add(BriefShare(brief_id=shared.id, shared_user_id=admin.id))
    await session.flush()

    for brief in (own, shared):
        await brief_central.get_brief(
            brief_id=brief.id, request=REQUEST, user=admin, session=session
        )

    assert audit == []


async def test_other_users_still_cannot_open_unshared_briefs(session, audit):
    alice, bob = await _user(session, "alice"), await _user(session, "bob")
    brief = await _brief(session, alice, "Alice brief")
    await _expect_404(
        brief_central.get_brief(
            brief_id=brief.id, request=REQUEST, user=bob, session=session
        )
    )
    await _expect_404(
        brief_central.copy_brief(
            brief_id=brief.id, request=REQUEST, user=bob, session=session
        )
    )
    assert audit == []


async def test_admin_copies_any_brief_into_their_own(session, audit):
    admin = await _user(session, "admin", superuser=True)
    alice = await _user(session, "alice")
    original = await _brief(session, alice, "Alice brief")
    session.add(BriefShare(brief_id=original.id, shared_user_id=alice.id))
    await session.flush()

    copied = await brief_central.copy_brief(
        brief_id=original.id, request=REQUEST, user=admin, session=session
    )

    assert copied.id != original.id
    assert (copied.user_id, copied.can_edit) == (admin.id, True)
    assert copied.title == "Alice brief (copy)"
    assert copied.content["title"] == "Alice brief (copy)"
    assert copied.content["sections"] == original.content["sections"]
    # Its own activity record, and no shares carried over.
    assert "activityId" not in copied.content
    assert copied.shared_with == []
    assert original.content["activityId"] == "act-original"
    assert [e for e, _ in audit] == [brief_central.EVENT_BRIEF_ADMIN_COPIED]
    listed = await brief_central.list_briefs(user=admin, session=session)
    assert copied.id in [b.id for b in listed]


async def test_a_viewer_of_a_shared_brief_cannot_copy_it(session):
    alice, bob = await _user(session, "alice"), await _user(session, "bob")
    brief = await _brief(session, alice, "Alice brief")
    session.add(BriefShare(brief_id=brief.id, shared_user_id=bob.id))
    await session.flush()
    await _expect_404(
        brief_central.copy_brief(
            brief_id=brief.id, request=REQUEST, user=bob, session=session
        )
    )


async def test_an_owner_can_copy_their_own_brief(session, audit):
    alice = await _user(session, "alice")
    brief = await _brief(session, alice, "Alice brief")
    copied = await brief_central.copy_brief(
        brief_id=brief.id, request=REQUEST, user=alice, session=session
    )
    assert copied.user_id == alice.id
    assert audit == []
    rows = await session.execute(select(Brief).where(Brief.user_id == alice.id))
    assert len(rows.scalars().all()) == 2
