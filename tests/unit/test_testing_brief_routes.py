"""Unit tests for the brief citation check routes (DB and runner faked)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from starlette.requests import Request

from ui.backend.routes import testing as routes
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
limiter.enabled = False

NOW = datetime.now(timezone.utc)
BRIEF_CONTENT = convert_legacy(
    {
        "sections": [
            {
                "title": "S",
                "status": "done",
                "content": "A fact [1]. Another [1].",
                "sources": [
                    {
                        "index": 1,
                        "title": "Doc",
                        "text": "text",
                        "chunkId": "c1",
                        "docId": "d1",
                    }
                ],
            }
        ]
    }
)[0]


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
    """``result.scalars()``: iterable, with ``.all()`` and ``.first()``."""

    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


class FakeSession:
    """Answers the route helpers' queries from in-memory lists."""

    def __init__(self, own, shared, checks=(), users=(), others=(), versions=()):
        self.own, self.shared, self.checks, self.users = (
            list(own),
            list(shared),
            list(checks),
            list(users),
        )
        # Every brief not owned by the user: what the admin-only "others"
        # query returns (shared briefs included, like the real table).
        self.others = list(shared) + list(others)
        # brief_versions rows: (brief id, number) pairs become version rows.
        self.versions = [
            SimpleNamespace(id=uuid.uuid4(), brief_id=b, number=n) for b, n in versions
        ]
        self.added, self.deleted, self.commits = [], [], 0

    def _version_rows(self, text):
        """``latest_numbers`` reads (brief id, max number) tuples; the
        store's other reads want the newest row first."""
        if "max(" in text:
            numbers = {}
            for v in self.versions:
                numbers[v.brief_id] = max(numbers.get(v.brief_id, 0), v.number)
            return list(numbers.items())
        return sorted(self.versions, key=lambda v: -v.number)

    async def execute(self, statement):
        text = str(statement)
        if "FROM briefs JOIN brief_shares" in text:
            rows = self.shared
        elif "FROM briefs" in text:
            rows = self.others if "!=" in text else self.own
        elif "FROM brief_citation_checks" in text:
            checks = self.checks
            statuses = statement.compile().params.get("status_1")
            if isinstance(statuses, list):
                checks = [c for c in checks if c.status in statuses]
            rows = sorted(checks, key=lambda c: c.created_at, reverse=True)
        elif "FROM brief_versions" in text:
            rows = self._version_rows(text)
        elif "FROM users" in text or "FROM user_group_members" in text:
            rows = self.users if "FROM users" in text else []
        elif "FROM user_groups JOIN user_group_members" in text:
            # The admin's groups, read for their judge choice: none here.
            rows = []
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
        self.added.append(row)
        if type(row).__name__ == "BriefVersion":
            self.versions.append(row)
            return
        row.created_at = NOW
        self.checks.append(row)

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row, attribute_names=None, with_for_update=False):
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
        brief_version_id=uuid.uuid4(),
        brief_version_number=3,
        section_results=None,
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
        session = FakeSession(
            [mine], [theirs], [old, new], [me, other], versions=[(mine.id, 4)]
        )
        out = await routes.list_checkable_briefs(_request(), admin=me, session=session)
        by_title = {c.title: c for c in out}
        assert by_title["Mine"].access == "own"
        assert by_title["Theirs"].access == "shared"
        assert (
            by_title["Mine"].cited_passages == 2
            and by_title["Mine"].researched_sections == 1
        )
        assert by_title["Mine"].last_check.id == new.id
        assert by_title["Theirs"].last_check is None
        assert by_title["Mine"].owner_name == "Jan"
        # The check judged version 3; the brief is at version 4 since.
        last = by_title["Mine"].last_check
        assert last.brief_version_number == 3 and last.brief_changed is True

    @pytest.mark.asyncio
    async def test_list_when_check_predates_versions_then_changed_unknown(self):
        me = _user()
        mine = _brief(me.id, "Mine")
        check = _check(mine, brief_version_id=None, brief_version_number=None)
        session = FakeSession([mine], [], [check], [me])
        out = await routes.list_checkable_briefs(_request(), admin=me, session=session)
        last = out[0].last_check
        assert last.brief_version_number is None and last.brief_changed is None

    @pytest.mark.asyncio
    async def test_list_when_admin_then_other_users_briefs_included_once(self):
        me, other = _user(), _user()
        mine, theirs = _brief(me.id, "Mine"), _brief(other.id, "Theirs")
        unshared = _brief(other.id, "Unshared")
        session = FakeSession([mine], [theirs], [], [me, other], others=[unshared])
        out = await routes.list_checkable_briefs(_request(), admin=me, session=session)
        assert [c.title for c in out].count("Theirs") == 1
        by_title = {c.title: c for c in out}
        assert by_title["Theirs"].access == "shared"
        assert by_title["Unshared"].access == "other"
        assert by_title["Unshared"].owner_name == "Jan"

    @pytest.mark.asyncio
    async def test_list_when_not_admin_then_only_own_and_shared(self):
        me, other = _user(superuser=False), _user()
        mine, theirs = _brief(me.id, "Mine"), _brief(other.id, "Theirs")
        unshared = _brief(other.id, "Unshared")
        session = FakeSession([mine], [theirs], [], [me, other], others=[unshared])
        out = await routes.list_checkable_briefs(_request(), admin=me, session=session)
        assert sorted(c.title for c in out) == ["Mine", "Theirs"]


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
        monkeypatch.setattr(
            routes.brief_check_runs, "model_combo_names", lambda: ["Azure Foundry"]
        )
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
        monkeypatch.setattr(
            routes.brief_check_runs, "resolve_judge_model", lambda combo: None
        )
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
        monkeypatch.setattr(
            routes.brief_check_runs, "model_combo_names", lambda: ["Azure Foundry"]
        )
        monkeypatch.setattr(
            routes.brief_check_runs,
            "resolve_judge_model",
            lambda combo: f"judge-for-{combo}",
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
        assert check.check_kind == "full"
        assert check.created_by_user_id == me.id and check.brief_title == brief.title
        assert len(tasks.tasks) == 1 and tasks.tasks[0].args == (check.id,)
        # A brief with no version yet gets its baseline version, which the
        # check pins, in the same transaction.
        version = next(r for r in session.added if type(r).__name__ == "BriefVersion")
        assert (version.number, version.kind) == (1, "baseline")
        assert (
            version.content["sections"][0]["id"] == BRIEF_CONTENT["sections"][0]["id"]
        )
        assert check.brief_version_id == version.id and check.brief_version_number == 1
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_create_when_brief_has_versions_then_the_current_one_is_pinned(
        self, monkeypatch
    ):
        me = _user()
        brief = _brief(me.id)
        monkeypatch.setattr(
            routes.brief_check_runs, "resolve_judge_model", lambda combo: "judge"
        )
        session = FakeSession([brief], [], versions=[(brief.id, 1), (brief.id, 2)])
        check = await routes.create_brief_check(
            _request(),
            routes.BriefCitationCheckCreate(brief_id=brief.id),
            BackgroundTasks(),
            admin=me,
            session=session,
        )
        current = max(session.versions, key=lambda v: v.number)
        assert check.brief_version_id == current.id and check.brief_version_number == 2
        assert not any(type(r).__name__ == "BriefVersion" for r in session.added)


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
            routes,
            "build_review_workbook",
            lambda passages, by_section, sections: b"PK-fake",
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


@pytest.mark.asyncio
async def test_check_start_joins_an_active_version_before_scheduling_work():
    owner = _user()
    brief = _brief(owner.id)
    run = SimpleNamespace(id=uuid.uuid4(), created_at=NOW, status="running")
    session = FakeSession([brief], [], checks=[run])
    tasks = BackgroundTasks()
    assert (
        await routes.brief_check_runs.start(
            session, brief, owner, None, tasks, from_document=True
        )
        is run
    )
    assert tasks.tasks == [] and session.added == []


def test_document_check_states_follow_access_content_and_completed_version():
    brief = _brief(_user().id)
    state = {"marks": [], "current_version": 2, "brief_version": None}
    reason = routes.brief_check_runs.start_disabled_reason
    assert reason(brief, True, state) is None
    assert "read-only" in reason(brief, False, state)
    state.update(marks=[{}], brief_version=2)
    assert "already been checked" in reason(brief, True, state)
    state.update(current_version=3)
    assert reason(brief, True, state) is None
    brief.content = {"sections": []}
    assert "Write a section" in reason(brief, True, state)


@pytest.mark.asyncio
async def test_unchanged_document_cannot_start_another_run(monkeypatch):
    from unittest.mock import AsyncMock

    from ui.backend.services import brief_fact_check

    user = _user()
    brief = _brief(user.id)
    check = {"marks": [{}], "current_version": 4, "brief_version": 4}
    monkeypatch.setattr(brief_fact_check, "fact_check", AsyncMock(return_value=check))
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc:
        await routes.brief_check_runs.start(
            FakeSession([brief], []), brief, user, None, tasks, from_document=True
        )
    assert exc.value.status_code == 409 and not tasks.tasks


@pytest.mark.asyncio
async def test_shared_reader_cannot_start_or_stop_a_document_check():
    from ui.backend.routes import brief_central

    viewer = _user(superuser=False)
    brief = _brief(uuid.uuid4())
    session = FakeSession([], [brief])
    with pytest.raises(HTTPException) as exc:
        await brief_central.start_fact_check(
            brief.id,
            brief_central.BriefCheckStart(),
            _request(),
            BackgroundTasks(),
            user=viewer,
            session=session,
        )
    assert exc.value.status_code == 404 and not session.added
    with pytest.raises(HTTPException) as exc:
        await brief_central.stop_fact_check(
            brief.id, uuid.uuid4(), _request(), user=viewer, session=session
        )
    assert exc.value.status_code == 404 and session.commits == 0
