"""Unit tests for brief comments: schema validation, serialisation, permissions.

The route handlers are exercised against fakes for the session and models, so
these run without a database — same approach as test_brief_central.py.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    BriefCommentCreate,
    BriefCommentRead,
    BriefCommentUpdate,
)
from ui.backend.routes.brief_central import (
    _comment_author_name,
    create_brief_comment,
    delete_brief_comment,
    update_brief_comment,
)

pytestmark = pytest.mark.unit


class FakeUser:
    def __init__(self, email="a@b.org", first_name=None, last_name=None, uid=None):
        self.id = uid or uuid.uuid4()
        self.email = email
        self.first_name = first_name
        self.last_name = last_name


class FakeComment:
    """Stands in for the BriefComment ORM row."""

    def __init__(self, brief_id, user_id, body="hi", parent_id=None, resolved=False):
        self.id = uuid.uuid4()
        self.brief_id = brief_id
        self.user_id = user_id
        self.parent_id = parent_id
        self.section_id = "sec-1"
        self.quote = "cash transfers"
        self.quote_prefix = "on "
        self.quote_suffix = " improved"
        self.body = body
        self.resolved = resolved
        self.resolved_by_id = None
        self.resolved_at = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class FakeSession:
    """Minimal AsyncSession: get() by id, plus no-op persistence calls."""

    def __init__(self, objects=None):
        self.objects = objects or {}
        self.added = []
        self.deleted = []
        self.committed = False

    async def get(self, _model, key):
        return self.objects.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        # SQLAlchemy applies column defaults on flush; mirror that so a
        # freshly-created row serialises as it does in production.
        now = datetime.now(timezone.utc)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "resolved", None) is None:
            obj.resolved = False
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    async def delete(self, obj):
        self.deleted.append(obj)


@pytest.fixture
def patch_access(monkeypatch):
    """Patch the brief-access check; returns a setter for (found, is_owner)."""

    def _set(found=True, is_owner=True):
        async def fake(_session, brief_id, _user):
            if not found:
                raise HTTPException(status_code=404, detail="Brief not found")
            return object(), is_owner

        monkeypatch.setattr(
            "ui.backend.routes.brief_central._get_viewable_brief", fake
        )

    return _set


class TestCommentSchemas:
    def test_valid_create(self):
        c = BriefCommentCreate(body="Needs a source", section_id="sec-1", quote="x")
        assert c.body == "Needs a source"
        assert c.parent_id is None

    def test_body_required_nonempty(self):
        with pytest.raises(ValidationError):
            BriefCommentCreate(body="")

    def test_body_length_capped(self):
        with pytest.raises(ValidationError):
            BriefCommentCreate(body="x" * 5001)

    def test_quote_length_capped(self):
        with pytest.raises(ValidationError):
            BriefCommentCreate(body="ok", quote="x" * 2001)

    def test_update_all_optional(self):
        u = BriefCommentUpdate()
        assert u.body is None and u.resolved is None

    def test_update_rejects_empty_body(self):
        with pytest.raises(ValidationError):
            BriefCommentUpdate(body="")

    def test_read_round_trip(self):
        now = datetime.now(timezone.utc)
        r = BriefCommentRead(
            id=uuid.uuid4(),
            brief_id=uuid.uuid4(),
            body="hi",
            resolved=False,
            author_name="Ada",
            author_email="ada@x.org",
            is_mine=True,
            created_at=now,
            updated_at=now,
        )
        assert r.author_name == "Ada"
        assert r.parent_id is None


class TestAuthorName:
    def test_prefers_full_name(self):
        assert _comment_author_name(FakeUser("a@b.org", "Ada", "Lovelace")) == (
            "Ada Lovelace"
        )

    def test_falls_back_to_email(self):
        assert _comment_author_name(FakeUser("a@b.org")) == "a@b.org"

    def test_partial_name(self):
        assert _comment_author_name(FakeUser("a@b.org", "Ada", None)) == "Ada"

    def test_missing_author(self):
        assert _comment_author_name(None) == "Unknown"


class TestCreateComment:
    @pytest.mark.asyncio
    async def test_viewer_can_comment(self, patch_access):
        patch_access(is_owner=False)
        user = FakeUser()
        session = FakeSession()
        brief_id = uuid.uuid4()
        out = await create_brief_comment(
            brief_id, BriefCommentCreate(body="Please cite"), user, session
        )
        assert out.body == "Please cite"
        assert out.is_mine is True
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_no_access_is_404(self, patch_access):
        patch_access(found=False)
        with pytest.raises(HTTPException) as exc:
            await create_brief_comment(
                uuid.uuid4(), BriefCommentCreate(body="x"), FakeUser(), FakeSession()
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reply_to_other_brief_rejected(self, patch_access):
        patch_access()
        user = FakeUser()
        parent = FakeComment(brief_id=uuid.uuid4(), user_id=user.id)
        session = FakeSession({parent.id: parent})
        with pytest.raises(HTTPException) as exc:
            await create_brief_comment(
                uuid.uuid4(),
                BriefCommentCreate(body="x", parent_id=parent.id),
                user,
                session,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_threads_stay_one_level_deep(self, patch_access):
        patch_access()
        user = FakeUser()
        brief_id = uuid.uuid4()
        reply = FakeComment(brief_id, user.id, parent_id=uuid.uuid4())
        session = FakeSession({reply.id: reply})
        with pytest.raises(HTTPException) as exc:
            await create_brief_comment(
                brief_id,
                BriefCommentCreate(body="x", parent_id=reply.id),
                user,
                session,
            )
        assert exc.value.status_code == 404


class TestUpdateComment:
    @pytest.mark.asyncio
    async def test_author_can_edit_body(self, patch_access):
        patch_access(is_owner=False)
        user = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, user.id, body="old")
        session = FakeSession({comment.id: comment})
        out = await update_brief_comment(
            brief_id, comment.id, BriefCommentUpdate(body="new"), user, session
        )
        assert out.body == "new"

    @pytest.mark.asyncio
    async def test_non_author_cannot_edit_body(self, patch_access):
        patch_access(is_owner=True)
        owner = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, uuid.uuid4(), body="theirs")
        session = FakeSession({comment.id: comment})
        with pytest.raises(HTTPException) as exc:
            await update_brief_comment(
                brief_id, comment.id, BriefCommentUpdate(body="edited"), owner, session
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_brief_owner_can_resolve_others_comment(self, patch_access):
        patch_access(is_owner=True)
        owner = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, uuid.uuid4())
        session = FakeSession({comment.id: comment})
        out = await update_brief_comment(
            brief_id, comment.id, BriefCommentUpdate(resolved=True), owner, session
        )
        assert out.resolved is True
        assert comment.resolved_by_id == owner.id
        assert comment.resolved_at is not None

    @pytest.mark.asyncio
    async def test_viewer_cannot_resolve_others_comment(self, patch_access):
        patch_access(is_owner=False)
        viewer = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, uuid.uuid4())
        session = FakeSession({comment.id: comment})
        with pytest.raises(HTTPException) as exc:
            await update_brief_comment(
                brief_id, comment.id, BriefCommentUpdate(resolved=True), viewer, session
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reopening_clears_resolution(self, patch_access):
        patch_access(is_owner=False)
        user = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, user.id, resolved=True)
        comment.resolved_by_id = user.id
        comment.resolved_at = datetime.now(timezone.utc)
        session = FakeSession({comment.id: comment})
        out = await update_brief_comment(
            brief_id, comment.id, BriefCommentUpdate(resolved=False), user, session
        )
        assert out.resolved is False
        assert comment.resolved_by_id is None
        assert comment.resolved_at is None

    @pytest.mark.asyncio
    async def test_comment_from_another_brief_is_404(self, patch_access):
        patch_access()
        user = FakeUser()
        comment = FakeComment(uuid.uuid4(), user.id)
        session = FakeSession({comment.id: comment})
        with pytest.raises(HTTPException) as exc:
            await update_brief_comment(
                uuid.uuid4(), comment.id, BriefCommentUpdate(body="x"), user, session
            )
        assert exc.value.status_code == 404


class TestDeleteComment:
    @pytest.mark.asyncio
    async def test_author_can_delete(self, patch_access):
        patch_access(is_owner=False)
        user = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, user.id)
        session = FakeSession({comment.id: comment})
        await delete_brief_comment(brief_id, comment.id, user, session)
        assert session.deleted == [comment]

    @pytest.mark.asyncio
    async def test_brief_owner_can_delete_any(self, patch_access):
        patch_access(is_owner=True)
        owner = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, uuid.uuid4())
        session = FakeSession({comment.id: comment})
        await delete_brief_comment(brief_id, comment.id, owner, session)
        assert session.deleted == [comment]

    @pytest.mark.asyncio
    async def test_viewer_cannot_delete_others(self, patch_access):
        patch_access(is_owner=False)
        viewer = FakeUser()
        brief_id = uuid.uuid4()
        comment = FakeComment(brief_id, uuid.uuid4())
        session = FakeSession({comment.id: comment})
        with pytest.raises(HTTPException) as exc:
            await delete_brief_comment(brief_id, comment.id, viewer, session)
        assert exc.value.status_code == 403
