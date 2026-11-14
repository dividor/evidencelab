"""Unit tests for the brief version routes and the versions every Brief
Central save writes (sessions faked)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ui.backend.auth.schemas import BriefRunCreate, BriefUpdate
from ui.backend.routes import brief_central, brief_citations, brief_versions
from ui.backend.services import brief_citations as bc
from ui.backend.utils.app_limits import limiter

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("one_data_source")]
limiter.enabled = False

NOW = datetime.now(timezone.utc)


def src(index, chunk):
    return {
        "chunkId": chunk,
        "docId": "d1",
        "title": "Doc",
        "text": "t",
        "index": index,
    }


def content_with_one_run():
    content = {
        "citationsVersion": 2,
        "title": "B",
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [{"id": "a", "title": "A", "level": 1, "status": "pending"}],
    }
    bc.record_run(
        content,
        "a",
        {"mode": "generate", "content": "One [1].", "sources": [src(1, "c1")]},
    )
    return content


def user(superuser=False):
    return SimpleNamespace(
        id=uuid.uuid4(), is_superuser=superuser, full_name="Jan", email="j@x"
    )


def brief_of(owner, content):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=owner.id,
        title="B",
        query=None,
        data_source="wfp",
        voice_profile_id=None,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


def request():
    from fastapi import FastAPI, Request

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


class Session:
    """One brief, its versions and its owner, in memory."""

    def __init__(self, brief, owner, shared=False):
        self.brief, self.owner, self.shared = brief, owner, shared
        self.versions = []
        self.commits = 0

    def _rows(self, statement):
        text = str(statement)
        if "FROM brief_versions" in text:
            rows = sorted(self.versions, key=lambda r: -r.number)
            numbers = [
                v
                for k, v in statement.compile().params.items()
                if k.startswith("number")
            ]
            return [r for r in rows if r.number == numbers[0]] if numbers else rows
        if "FROM brief_shares" in text:
            return [object()] if self.shared else []
        if "FROM briefs" in text:
            return [self.brief]
        if "FROM users" in text:
            return [self.owner]
        return []

    async def execute(self, statement):
        rows = self._rows(statement)
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(
                first=lambda: rows[0] if rows else None,
                all=lambda: rows,
                unique=lambda: SimpleNamespace(all=lambda: rows),
            ),
            all=lambda: rows,
        )

    async def get(self, model, key):
        return self.owner if key == self.owner.id else None

    def add(self, row):
        if type(row).__name__ == "BriefVersion":
            self.versions.append(row)

    async def delete(self, row):
        self.versions.remove(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, row, attribute_names=None):
        pass


async def run(session, brief, owner, text, review=False):
    return await brief_citations.record_section_run(
        brief.id,
        "a",
        BriefRunCreate(
            mode="generate", content=text, sources=[src(1, "c2")], review=review
        ),
        owner,
        session,
    )


class TestVersionsWrittenBySaves:
    @pytest.mark.asyncio
    async def test_run_reject_and_keep_write_the_versions_they_should(self):
        owner = user()
        brief = brief_of(owner, content_with_one_run())
        session = Session(brief, owner)
        read = await run(session, brief, owner, "Two [1].", review=True)
        section = read.content["sections"][0]
        assert section["pendingReview"]["before"] == "One [1]."
        await brief_citations.reject_section_run(
            brief.id, "a", section["currentRunId"], owner, session
        )
        assert [(v.number, v.kind) for v in session.versions] == [
            (1, "baseline"),
            (2, "generate"),
            (3, "reject"),
        ]
        assert session.versions[1].summary == "Regenerated “A”"
        assert session.versions[2].summary == "Rejected the changes to “A”"
        # The first version keeps the time the brief was last saved before.
        assert session.versions[0].created_at == NOW
        read = await run(session, brief, owner, "Three [1].", review=True)
        run_id = read.content["sections"][0]["currentRunId"]
        await brief_citations.keep_section_run(
            request(), brief.id, "a", run_id, owner, session
        )
        # Keep ends the review; the brief's text is unchanged, so no version.
        assert len(session.versions) == 4
        assert "pendingReview" not in bc.find_section(brief.content, "a")

    @pytest.mark.asyncio
    async def test_browser_save_is_described_by_the_api(self):
        owner = user()
        brief = brief_of(owner, content_with_one_run())
        session = Session(brief, owner)
        await brief_central.update_brief(
            brief.id,
            BriefUpdate(
                content={
                    "citationsVersion": 2,
                    "sections": [{"id": "a", "title": "Renamed", "level": 1}],
                }
            ),
            owner,
            session,
        )
        assert session.versions[-1].summary == "Renamed “A” to “Renamed”"


class TestVersionRoutes:
    @pytest.mark.asyncio
    async def test_list_detail_and_restore(self):
        owner = user()
        brief = brief_of(owner, content_with_one_run())
        session = Session(brief, owner)
        await run(session, brief, owner, "Two [1].")
        listed = await brief_versions.list_brief_versions(
            request(), brief.id, owner, session
        )
        assert [(v["number"], v["is_current"]) for v in listed] == [
            (2, True),
            (1, False),
        ]
        detail = await brief_versions.get_brief_version(
            request(), brief.id, 2, owner, session
        )
        row = detail["sections"][0]
        assert (row["change"], row["before"], row["after"]) == (
            "changed",
            "One [1].",
            "Two [1].",
        )
        assert detail["can_restore"] is False  # it is the current version
        await brief_versions.restore_brief_version(
            request(), brief.id, 1, owner, session
        )
        assert bc.find_section(brief.content, "a")["renumbered"]["content"] == (
            "One [1]."
        )
        assert session.versions[-1].summary == "Restored the whole brief to version 1"
        with pytest.raises(HTTPException) as exc:
            await brief_versions.restore_brief_version(
                request(), brief.id, 3, owner, session
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_viewer_reads_versions_but_cannot_restore(self):
        owner, viewer = user(), user()
        brief = brief_of(owner, content_with_one_run())
        session = Session(brief, owner)
        await run(session, brief, owner, "Two [1].")
        session.shared = True
        detail = await brief_versions.get_brief_version(
            request(), brief.id, 1, viewer, session
        )
        assert detail["can_restore"] is False
        session.brief = None  # the owner-only lookup finds nothing for a viewer
        with pytest.raises(HTTPException) as exc:
            await brief_versions.restore_brief_version(
                request(), brief.id, 1, viewer, session
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_restore_section_version_route(self):
        owner = user()
        brief = brief_of(owner, content_with_one_run())
        session = Session(brief, owner)
        await run(session, brief, owner, "Two [1].")
        read = await brief_citations.restore_section_version(
            request(), brief.id, "a", "a-r1", owner, session
        )
        assert read.content["sections"][0]["renumbered"]["content"] == "One [1]."
        assert session.versions[-1].kind == "restore"
        assert session.versions[-1].summary == "Restored an earlier version of “A”"
