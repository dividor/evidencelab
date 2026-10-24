"""Unit tests for the Activity log's brief row writer."""

import uuid
from types import SimpleNamespace

import pytest

from ui.backend.services import brief_activity
from ui.backend.services import brief_citations as bc

pytestmark = pytest.mark.unit


def _content(activity_id):
    content = {
        "citationsVersion": 2,
        "title": "Brief",
        "activityId": activity_id,
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [
            {"id": "a", "title": "Alpha", "level": 1, "status": "pending"},
            {"id": "b", "title": "Beta", "level": 1, "status": "pending"},
        ],
    }
    bc.record_run(
        content,
        "a",
        {
            "mode": "generate",
            "content": "One [2]. Two [1].",
            "sources": [
                {
                    "chunkId": "c1",
                    "docId": "d1",
                    "title": "Doc 1",
                    "text": "T1",
                    "page": 3,
                    "index": 1,
                    "pdfUrl": "https://x/1.pdf",
                },
                {
                    "chunkId": "c2",
                    "docId": "d2",
                    "title": "Doc 2",
                    "text": "T2",
                    "page": 7,
                    "index": 2,
                },
            ],
        },
    )
    return content


class FakeSession:
    def __init__(self, rows=()):
        self.rows, self.added = list(rows), []

    async def execute(self, statement):
        rows = self.rows
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(first=lambda: rows[0] if rows else None)
        )

    def add(self, row):
        self.added.append(row)


class TestRenderers:
    def test_markdown_uses_renumbered_text_for_every_section(self):
        md = brief_activity.brief_markdown(_content(str(uuid.uuid4())))
        assert md == "## Alpha\n\nOne [1]. Two [2].\n\n## Beta"

    def test_search_results_follow_the_references_list(self):
        rows = brief_activity.brief_search_results(_content(str(uuid.uuid4())))
        assert [
            (r["n"], r["chunk_id"], r["page_num"], r["chunk_text"]) for r in rows
        ] == [
            (1, "c2", 7, "T2"),
            (2, "c1", 3, "T1"),
        ]
        assert rows[1]["link"] == "https://x/1.pdf"


class TestUpsert:
    @pytest.mark.asyncio
    async def test_inserts_a_row_for_the_owner(self):
        activity_id = str(uuid.uuid4())
        session = FakeSession()
        user_id = uuid.uuid4()
        brief_id = uuid.uuid4()
        row = await brief_activity.upsert_brief_activity(
            session,
            content=_content(activity_id),
            title="Brief",
            brief_id=brief_id,
            user_id=user_id,
        )
        assert session.added == [row]
        assert row.user_id == user_id and row.session_id is None
        assert str(row.search_id) == activity_id
        assert row.filters == {"type": "brief", "brief_id": str(brief_id)}
        assert row.ai_summary.startswith("## Alpha")
        assert len(row.search_results) == 2

    @pytest.mark.asyncio
    async def test_updates_an_existing_row_and_keeps_other_filters(self):
        activity_id = str(uuid.uuid4())
        existing = SimpleNamespace(
            filters={"timing": {"x": 1}},
            query="old",
            search_results=None,
            ai_summary=None,
        )
        session = FakeSession([existing])
        row = await brief_activity.upsert_brief_activity(
            session,
            content=_content(activity_id),
            title="New title",
            brief_id=None,
            user_id=None,
            session_id="anon-1",
        )
        assert row is existing and session.added == []
        assert existing.query == "New title"
        assert existing.filters == {"timing": {"x": 1}, "type": "brief"}
        assert "[1]" in existing.ai_summary

    @pytest.mark.asyncio
    async def test_skips_without_activity_id_or_owner(self):
        content = _content(str(uuid.uuid4()))
        assert (
            await brief_activity.upsert_brief_activity(
                FakeSession(), content=content, title="t", brief_id=None, user_id=None
            )
            is None
        )
        content["activityId"] = "not-a-uuid"
        assert (
            await brief_activity.upsert_brief_activity(
                FakeSession(),
                content=content,
                title="t",
                brief_id=None,
                user_id=uuid.uuid4(),
            )
            is None
        )
