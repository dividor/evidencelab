"""Unit tests for the brief citation check routes (DB and runner faked)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from starlette.requests import Request

from ui.backend.routes import testing as routes
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
limiter.enabled = False

NOW = datetime.now(timezone.utc)
BRIEF_CONTENT = {
    "sections": [
        {
            "title": "S",
            "status": "done",
            "content": "A fact [1]. Another [1].",
            "sources": [{"index": 1, "title": "Doc", "text": "text"}],
        }
    ]
}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1),
            "app": FastAPI(),
        }
    )


def _user(superuser=True):
    return SimpleNamespace(
        id=uuid.uuid4(), is_superuser=superuser, full_name="Jan", email="j@x"
    )


def _brief(owner_id, title="B"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=owner_id,
        title=title,
        data_source="wfp",
        content=BRIEF_CONTENT,
        updated_at=NOW,
        created_at=NOW,
    )


class FakeScalars(list):
    """``result.scalars()``: iterable, with ``.all()``."""

    def all(self):
        return list(self)


class FakeSession:
    """Answers the route helpers' queries from in-memory lists."""

    def __init__(self, own, shared, checks=(), users=()):
        self.own, self.shared, self.checks, self.users = (
            list(own),
            list(shared),
            list(checks),
            list(users),
        )
        self.added, self.deleted, self.commits = [], [], 0

    async def execute(self, statement):
        text = str(statement)
        if "FROM briefs JOIN brief_shares" in text:
            rows = self.shared
        elif "FROM briefs" in text:
            rows = self.own
        elif "FROM brief_citation_checks" in text:
            rows = sorted(self.checks, key=lambda c: c.created_at, reverse=True)
        elif "FROM users" in text or "FROM user_group_members" in text:
            rows = self.users if "FROM users" in text else []
        else:
            raise AssertionError(f"unexpected query: {text[:80]}")
        result = SimpleNamespace(
            scalars=lambda: FakeScalars(rows), all=lambda: list(rows)
        )
        # Like SQLAlchemy: a joined-eager-load result (users) must be unique()'d first.
        if "FROM users" in text:
            return SimpleNamespace(unique=lambda: result)
        return result

    async def get(self, model, key):
        return next((c for c in self.checks if c.id == key), None)

    def add(self, row):
        row.id = uuid.uuid4()
        row.created_at = NOW
        self.added.append(row)
        self.checks.append(row)

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row, attribute_names=None):
        if (
            attribute_names
            and "passages" in attribute_names
            and not hasattr(row, "passages")
        ):
            row.passages = []


def _check(brief, status="completed", **over):
    fields = dict(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brief_title=brief.title,
        data_source="wfp",
        created_by_user_id=None,
        judge_model="m",
        model_combo=None,
        status=status,
        summary_stats={
            "total": 2,
            "flagged": 1,
            "flagged_share": 0.5,
            "by_section": [],
        },
        started_at=None,
        finished_at=None,
        created_at=NOW,
    )
    return SimpleNamespace(**{**fields, **over})


class TestListBriefs:
    @pytest.mark.asyncio
    async def test_list_when_own_and_shared_then_both_with_counts_and_last_check(self):
        me, other = _user(), _user()
        mine, theirs = _brief(me.id, "Mine"), _brief(other.id, "Theirs")
        old, new = _check(
            mine, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
        ), _check(mine)
        session = FakeSession([mine], [theirs], [old, new], [me, other])
        out = await routes.list_checkable_briefs(_request(), admin=me, session=session)
        by_title = {c.title: c for c in out}
        assert by_title["Mine"].shared is False and by_title["Theirs"].shared is True
        assert (
            by_title["Mine"].cited_passages == 2
            and by_title["Mine"].researched_sections == 1
        )
        assert by_title["Mine"].last_check.id == new.id
        assert by_title["Theirs"].last_check is None
        assert by_title["Mine"].owner_name == "Jan"


class TestCreateCheck:
    @pytest.mark.asyncio
    async def test_create_when_brief_not_accessible_then_404(self):
        me = _user()
        session = FakeSession([], [])
        body = routes.BriefCitationCheckCreate(brief_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            await routes.create_brief_check(
                _request(), body, BackgroundTasks(), admin=me, session=session
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_when_combo_unknown_then_400(self, monkeypatch):
        me = _user()
        brief = _brief(me.id)
        monkeypatch.setattr(routes, "_model_combo_names", lambda: ["Azure Foundry"])
        body = routes.BriefCitationCheckCreate(brief_id=brief.id, model_combo="Nope")
        with pytest.raises(HTTPException) as exc:
            await routes.create_brief_check(
                _request(),
                body,
                BackgroundTasks(),
                admin=me,
                session=FakeSession([brief], []),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_when_no_judge_model_then_503(self, monkeypatch):
        me = _user()
        brief = _brief(me.id)
        monkeypatch.setattr(routes, "resolve_judge_model", lambda combo: None)
        body = routes.BriefCitationCheckCreate(brief_id=brief.id)
        with pytest.raises(HTTPException) as exc:
            await routes.create_brief_check(
                _request(),
                body,
                BackgroundTasks(),
                admin=me,
                session=FakeSession([brief], []),
            )
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_when_shared_brief_then_pending_check_and_background_task(
        self, monkeypatch
    ):
        me, other = _user(), _user()
        brief = _brief(other.id)
        monkeypatch.setattr(routes, "_model_combo_names", lambda: ["Azure Foundry"])
        monkeypatch.setattr(
            routes, "resolve_judge_model", lambda combo: f"judge-for-{combo}"
        )
        session = FakeSession([], [brief])
        tasks = BackgroundTasks()
        body = routes.BriefCitationCheckCreate(
            brief_id=brief.id, model_combo="Azure Foundry"
        )
        check = await routes.create_brief_check(
            _request(), body, tasks, admin=me, session=session
        )
        assert (
            check.status == "pending" and check.judge_model == "judge-for-Azure Foundry"
        )
        assert check.created_by_user_id == me.id and check.brief_title == brief.title
        assert len(tasks.tasks) == 1 and tasks.tasks[0].args == (check.id,)


class TestCheckAccess:
    @pytest.mark.asyncio
    async def test_get_when_brief_belongs_to_someone_else_then_404(self):
        me, other = _user(), _user()
        brief = _brief(other.id)
        check = _check(brief)
        session = FakeSession([], [], [check])
        with pytest.raises(HTTPException) as exc:
            await routes.get_brief_check(
                _request(), check.id, admin=me, session=session
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_when_running_then_failed_with_message(self):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief, status="running")
        session = FakeSession([brief], [], [check])
        out = await routes.cancel_brief_check(
            _request(), check.id, admin=me, session=session
        )
        assert out.status == "failed" and out.summary_stats == {
            "error": "Cancelled by user"
        }

    @pytest.mark.asyncio
    async def test_cancel_when_completed_then_unchanged(self):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief)
        session = FakeSession([brief], [], [check])
        out = await routes.cancel_brief_check(
            _request(), check.id, admin=me, session=session
        )
        assert out.status == "completed" and session.commits == 0

    @pytest.mark.asyncio
    async def test_delete_when_owned_then_removed(self):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief)
        session = FakeSession([brief], [], [check])
        resp = await routes.delete_brief_check(
            _request(), check.id, admin=me, session=session
        )
        assert resp.status_code == 204 and session.deleted == [check]

    @pytest.mark.asyncio
    async def test_export_when_completed_then_xlsx_attachment(self, monkeypatch):
        me = _user()
        brief = _brief(me.id)
        check = _check(brief)
        check.passages = []
        monkeypatch.setattr(
            routes, "build_review_workbook", lambda passages, by_section: b"PK-fake"
        )
        session = FakeSession([brief], [], [check])
        resp = await routes.export_brief_check(
            _request(), check.id, admin=me, session=session
        )
        assert resp.body == b"PK-fake"
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="citation_check_{brief.id}.xlsx"'
        )
        assert "spreadsheetml" in resp.media_type
