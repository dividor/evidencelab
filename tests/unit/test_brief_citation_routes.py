"""Unit tests for the brief citation routes and the Brief Central save path
(sessions faked; the citation service itself is tested in
test_brief_citations.py)."""

import copy
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ui.backend.auth.schemas import (
    BriefCitationsOp,
    BriefCreate,
    BriefRunCreate,
    BriefUpdate,
)
from ui.backend.routes import brief_central, brief_citations
from ui.backend.services import brief_citations as bc
from ui.backend.services.brief_citations_convert import convert_legacy
from ui.backend.utils.app_limits import limiter

pytestmark = pytest.mark.unit
limiter.enabled = False

NOW = datetime.now(timezone.utc)
ACTIVITY_ID = str(uuid.uuid4())


def src(index, chunk, page=None):
    return {
        "chunkId": chunk,
        "docId": "d1",
        "title": "Doc",
        "text": f"Excerpt {chunk}",
        "score": 0.5,
        "page": page,
        "index": index,
    }


def v2_brief():
    content = {
        "citationsVersion": 2,
        "title": "B",
        "activityId": ACTIVITY_ID,
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [
            {"id": "a", "title": "A", "level": 1, "status": "pending"},
            {"id": "b", "title": "B", "level": 1, "status": "pending"},
        ],
    }
    bc.record_run(
        content,
        "a",
        {"mode": "generate", "content": "A [1].", "sources": [src(1, "c1", 4)]},
    )
    return content


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(), is_superuser=False, full_name="Jan", email="j@x"
    )


def _brief(user, content):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user.id,
        title="B",
        query=None,
        data_source="wfp",
        voice_profile_id=None,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


def _request():
    from fastapi import FastAPI, Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1),
            "app": FastAPI(),
        }
    )


class FakeScalars(list):
    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


class FakeSession:
    """Answers the brief lookup, the share list and the activity upsert."""

    def __init__(self, brief, user, activities=()):
        self.brief, self.user = brief, user
        self.activities = list(activities)
        self.added, self.commits = [], 0

    async def execute(self, statement):
        text = str(statement)
        if "FROM briefs" in text:
            rows = [self.brief]
        elif "FROM user_activity" in text:
            rows = list(self.activities)
        else:
            rows = []
        return SimpleNamespace(
            scalars=lambda: FakeScalars(rows), all=lambda: list(rows)
        )

    async def get(self, model, key):
        return self.user if key == self.user.id else None

    def add(self, row):
        self.added.append(row)
        if type(row).__name__ == "UserActivity":
            self.activities.append(row)
        else:
            row.id = uuid.uuid4()
            row.created_at = row.updated_at = NOW

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, row, attribute_names=None):
        pass


class TestRecordRun:
    @pytest.mark.asyncio
    async def test_record_run_stores_original_renumbers_and_writes_activity(self):
        user = _user()
        brief = _brief(user, v2_brief())
        session = FakeSession(brief, user)
        body = BriefRunCreate(
            mode="generate",
            content="B cites [1] and [2].",
            sources=[src(1, "c2", 9), src(2, "c1", 4)],
            run_id="run-xyz",
            question="B",
        )
        read = await brief_citations.record_section_run(
            brief.id, "b", body, user, session
        )

        stored = bc.find_section(brief.content, "b")
        assert stored["runs"][0]["content"] == "B cites [1] and [2]."
        assert stored["runs"][0]["runId"] == "run-xyz"
        assert stored["renumbered"]["content"] == "B cites [2] and [1]."
        # The response is the read model: originals summarised, sources expanded.
        section = read.content["sections"][1]
        assert "content" not in section["runs"][0]
        assert [s["index"] for s in section["renumbered"]["sources"]] == [2, 1]
        assert section["renumbered"]["sources"][0]["chunkId"] == "c2"
        assert "sources" not in read.content
        # The Activity row carries the renumbered text and the References list.
        activity = session.activities[0]
        assert str(activity.search_id) == ACTIVITY_ID
        assert activity.filters["type"] == "brief"
        assert "B cites [2] and [1]." in activity.ai_summary
        assert [r["chunk_id"] for r in activity.search_results] == ["c1", "c2"]
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_record_run_on_legacy_brief_is_a_conflict(self):
        user = _user()
        brief = _brief(user, {"sections": [{"content": "x [1]", "sources": []}]})
        body = BriefRunCreate(mode="generate", content="x", sources=[])
        with pytest.raises(HTTPException) as exc:
            await brief_citations.record_section_run(
                brief.id, "a", body, user, FakeSession(brief, user)
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_unknown_section_is_a_bad_request(self):
        user = _user()
        brief = _brief(user, v2_brief())
        body = BriefRunCreate(mode="generate", content="x", sources=[])
        with pytest.raises(HTTPException) as exc:
            await brief_citations.record_section_run(
                brief.id, "zz", body, user, FakeSession(brief, user)
            )
        assert exc.value.status_code == 400


class TestOtherOperations:
    @pytest.mark.asyncio
    async def test_grouping_reject_highlights_and_reads(self):
        user = _user()
        brief = _brief(user, v2_brief())
        session = FakeSession(brief, user)
        from ui.backend.auth.schemas import BriefGroupingUpdate, BriefHighlightsUpdate

        await brief_citations.set_reference_grouping(
            brief.id, BriefGroupingUpdate(grouping="document-single"), user, session
        )
        assert brief.content["referenceGrouping"] == "document-single"
        assert brief.content["references"][0]["page"] is None

        await brief_citations.set_source_highlights(
            brief.id,
            BriefHighlightsUpdate(highlights={"s1": [{"claim": "a", "matches": []}]}),
            user,
            session,
        )
        assert brief.content["sources"][0]["claimMatches"] == [
            {"claim": "a", "matches": []}
        ]

        detail = await brief_citations.get_section_run(
            brief.id, "a", "r1", user, session
        )
        assert detail["content"] == "A [1]." and detail["displayNumbers"] == {"1": 1}
        trace = await brief_citations.trace_citation(brief.id, "a", 1, user, session)
        assert trace["chunkId"] == "c1" and trace["agentIndices"] == [1]

        await brief_citations.record_section_run(
            brief.id,
            "a",
            BriefRunCreate(mode="edit", content="A edited [1]."),
            user,
            session,
        )
        await brief_citations.reject_section_run(brief.id, "a", "r2", user, session)
        assert bc.find_section(brief.content, "a")["renumbered"]["content"] == "A [1]."

    @pytest.mark.asyncio
    async def test_anonymous_op_returns_content_and_read_model(self, monkeypatch):
        monkeypatch.setattr(brief_citations, "USER_MODULE_ENABLED", False)
        content = v2_brief()
        body = BriefCitationsOp(
            content=content,
            op={
                "type": "run",
                "sectionId": "b",
                "run": {
                    "mode": "generate",
                    "content": "B [1].",
                    "sources": [src(1, "c1")],
                },
            },
        )
        out = await brief_citations.apply_citation_op(_request(), body, None)
        assert bc.find_section(out["content"], "b")["runs"][0]["content"] == "B [1]."
        assert out["read"]["sections"][1]["renumbered"]["content"] == "B [1]."
        assert "runs" in out["content"]["sections"][1]
        assert "content" not in out["read"]["sections"][1]["runs"][0]
        detail = await brief_citations.apply_citation_op(
            _request(),
            BriefCitationsOp(
                content=out["content"],
                op={"type": "run_detail", "sectionId": "b", "runId": "r2"},
            ),
            None,
        )
        assert detail["detail"]["content"] == "B [1]."
        legacy = {
            "sections": [
                {
                    "id": "x",
                    "title": "X",
                    "status": "done",
                    "content": "y [1]",
                    "sources": [src(1, "c3")],
                }
            ]
        }
        converted = await brief_citations.apply_citation_op(
            _request(), BriefCitationsOp(content=legacy, op={"type": "convert"}), None
        )
        assert converted["content"]["citationsVersion"] == 2
        with pytest.raises(HTTPException) as exc:
            await brief_citations.apply_citation_op(
                _request(), BriefCitationsOp(content=legacy, op={"type": "read"}), None
            )
        assert exc.value.status_code == 409


class TestBriefCentralSave:
    @pytest.mark.asyncio
    async def test_update_keeps_citation_facts_and_applies_structure(self):
        user = _user()
        brief = _brief(user, v2_brief())
        session = FakeSession(brief, user)
        body = BriefUpdate(
            content={
                "citationsVersion": 2,
                "title": "Renamed",
                "sections": [
                    {"id": "b", "title": "B first", "status": "pending"},
                    {
                        "id": "a",
                        "title": "A",
                        "status": "done",
                        "renumbered": {"content": "hack"},
                    },
                ],
                "sources": [],
                "references": [{"n": 1}],
            }
        )
        read = await brief_central.update_brief(brief.id, body, user, session)
        assert [s["id"] for s in brief.content["sections"]] == ["b", "a"]
        assert brief.content["title"] == "Renamed"
        assert bc.find_section(brief.content, "a")["renumbered"]["content"] == "A [1]."
        assert len(brief.content["sources"]) == 1
        assert read.content["references"][0]["source"]["chunkId"] == "c1"

    @pytest.mark.asyncio
    async def test_get_legacy_brief_is_a_conflict(self):
        user = _user()
        brief = _brief(user, {"sections": []})
        with pytest.raises(HTTPException) as exc:
            await brief_central.get_brief(
                brief.id, _request(), user, FakeSession(brief, user)
            )
        assert exc.value.status_code == 409

    def test_new_brief_content_converts_only_when_asked(self):
        legacy = {
            "sections": [
                {
                    "id": "a",
                    "title": "A",
                    "status": "done",
                    "content": "x [1]",
                    "sources": [src(1, "c1")],
                }
            ]
        }
        with pytest.raises(HTTPException) as exc:
            brief_central.new_brief_content(legacy, convert=False)
        assert exc.value.status_code == 409
        converted = brief_central.new_brief_content(legacy, convert=True)
        assert converted == convert_legacy(legacy)[0]

    def test_new_brief_content_keeps_a_stored_brief(self):
        stored = v2_brief()
        content = brief_central.new_brief_content(copy.deepcopy(stored), convert=False)
        assert bc.find_section(content, "a")["runs"][0]["content"] == "A [1]."
        assert content["references"] == stored["references"]

    def test_new_brief_content_applies_structure_with_template_text(self):
        content = brief_central.new_brief_content(
            {
                "citationsVersion": 2,
                "title": "T",
                "sections": [
                    {"id": "s", "title": "S", "status": "done", "content": "Given."}
                ],
            },
            convert=False,
        )
        assert bc.find_section(content, "s")["runs"][0]["mode"] == "manual"
        assert content["references"] == []

    @pytest.mark.asyncio
    async def test_create_brief_stores_computed_content(self):
        user = _user()
        session = FakeSession(SimpleNamespace(), user)
        body = BriefCreate(
            title="T",
            content={
                "citationsVersion": 2,
                "activityId": ACTIVITY_ID,
                "sections": [{"id": "s", "title": "S"}],
            },
        )
        read = await brief_central.create_brief(body, user, session)
        created = session.added[0]
        assert created.content["citationsVersion"] == 2
        assert read.content["sections"][0]["renumbered"]["content"] == ""
        assert session.activities[0].filters["type"] == "brief"

    def test_schema_run_payload_shape(self):
        body = BriefRunCreate(mode="edit", content="x", instruction="tighten")
        assert body.to_run() == {
            "mode": "edit",
            "content": "x",
            "sources": None,
            "instruction": "tighten",
        }
        with pytest.raises(ValueError):
            BriefRunCreate(mode="fly", content="x")
        assert BriefCreate(title="t", content={}).convert is False
