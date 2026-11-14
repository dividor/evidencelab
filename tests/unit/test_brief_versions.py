"""Unit tests for whole-brief versions: snapshots, describing and comparing
changes, restoring a brief, and the store (sessions faked)."""

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ui.backend.services import brief_citations as bc
from ui.backend.services import brief_version_store as store
from ui.backend.services import brief_versions as bv

pytestmark = pytest.mark.unit


def src(index, chunk):
    return {
        "chunkId": chunk,
        "docId": f"d-{chunk}",
        "title": f"Doc {chunk}",
        "text": "x" * 500,
        "index": index,
    }


def brief_with(*texts):
    content = {
        "citationsVersion": 2,
        "title": "Brief",
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [
            {"id": f"s{i}", "title": f"T{i}", "level": 1, "status": "pending"}
            for i in range(len(texts))
        ],
    }
    for i, text in enumerate(texts):
        bc.record_run(
            content,
            f"s{i}",
            {"mode": "generate", "content": text, "sources": [src(1, f"c{i}")]},
        )
    return content


def shown(content, sid):
    return bc.find_section(content, sid)["renumbered"]["content"]


class TestSnapshot:
    def test_snapshot_drops_source_records_and_log_text(self):
        content = brief_with("A [1].", "B [1].")
        snap = bv.snapshot(content)
        assert "sources" not in snap and "references" not in snap
        sec = snap["sections"][0]
        assert sec["run"]["content"] == "A [1]." and "sources" not in sec["run"]
        assert "after" not in sec["audit"][0] and "renumbered" not in sec
        assert len(json.dumps(snap)) < len(json.dumps(content)) / 2

    def test_materialise_rebuilds_the_display_text(self):
        content = brief_with("A [1].", "B [1].")
        rebuilt = bv.materialise(bv.snapshot(content), content["sources"])
        assert shown(rebuilt, "s1") == "B [2]."
        assert [r["sourceId"] for r in rebuilt["references"]] == ["s1", "s2"]

    def test_signature_ignores_browser_bookkeeping(self):
        content = brief_with("A [1].")
        before = bv.signature(bv.snapshot(content))
        content["date"] = 123
        content["sections"][0]["lastResearchedAt"] = 456
        assert bv.signature(bv.snapshot(content)) == before
        content["sections"][0]["title"] = "Renamed"
        assert bv.signature(bv.snapshot(content)) != before


class TestDescribeChange:
    def test_heading_changes(self):
        old = bv.snapshot(brief_with("A [1].", "B [1]."))
        content = brief_with("A [1].", "B [1].")
        content["sections"][0]["title"] = "Intro"
        content["sections"].append(
            {"id": "n", "title": "New", "level": 2, "status": "pending"}
        )
        kind, section_id, summary = bv.describe_change(old, bv.snapshot(content))
        assert kind == "structure" and section_id is None
        assert summary == "Added “New”; Renamed “T0” to “Intro”"

    def test_text_edited_by_hand_names_the_section(self):
        content = brief_with("A [1].", "B [1].")
        old = bv.snapshot(content)
        bc.record_run(content, "s1", {"mode": "manual", "content": "Typed [2]."})
        assert bv.describe_change(old, bv.snapshot(content)) == (
            "manual",
            "s1",
            "Edited “T1” by hand",
        )

    def test_settings(self):
        content = brief_with("A [1].")
        old = bv.snapshot(content)
        content["instructions"] = "Be brief"
        content["title"] = "New name"
        kind, _, summary = bv.describe_change(old, bv.snapshot(content))
        assert kind == "settings"
        assert summary == "Changed the brief prompt; Renamed the brief to “New name”"

    def test_summaries_for_runs_and_brief_events(self):
        assert bv.summarise("edit", "Findings") == "Edited “Findings” with AI"
        assert bv.summarise("brief-restore", detail="4") == (
            "Restored the whole brief to version 4"
        )


class TestCompare:
    def test_sections_added_removed_changed_in_reading_order(self):
        old = brief_with("A [1].", "B [1].", "C [1].")
        new = copy.deepcopy(old)
        new["sections"] = [s for s in new["sections"] if s["id"] != "s1"]
        new["sections"].append(
            {"id": "n", "title": "N", "level": 1, "status": "pending"}
        )
        bc.record_run(new, "s0", {"mode": "manual", "content": "A changed [1]."})
        bc.renumber(new)
        rows = bv.compare(old, new)["sections"]
        assert [(r["id"], r["change"]) for r in rows] == [
            ("s0", "changed"),
            ("s1", "removed"),
            ("s2", "changed"),  # renumbered: [3] became [2]
            ("n", "added"),
        ]
        assert (rows[0]["before"], rows[0]["after"]) == ("A [1].", "A changed [1].")
        assert rows[1]["before"] == "B [2]." and rows[1]["after"] is None

    def test_first_version_lists_everything_as_added(self):
        rows = bv.compare(None, brief_with("A [1]."))["sections"]
        assert rows[0]["change"] == "added" and rows[0]["after"] == "A [1]."


class TestRestoreBrief:
    def test_restore_brings_back_headings_text_and_settings_keeping_history(self):
        content = brief_with("A [1].", "B [1].")
        version = bv.snapshot(content)
        # Later: A regenerated, B removed, a heading added, the prompt set.
        bc.record_run(
            content,
            "s0",
            {"mode": "generate", "content": "A new [1].", "sources": [src(1, "c9")]},
        )
        content = bc.apply_structure(
            content,
            {
                "instructions": "Be brief",
                "sections": [
                    {"id": "s0", "title": "T0", "level": 1},
                    {"id": "n", "title": "N", "level": 1},
                ],
            },
        )
        restored = bv.restore_brief(content, version, 1, now_ms=10)
        assert [s["id"] for s in restored["sections"]] == ["s0", "s1"]
        assert shown(restored, "s0") == "A [1]." and shown(restored, "s1") == "B [2]."
        assert "instructions" not in restored
        s0 = bc.find_section(restored, "s0")
        # A's history is kept and gains a Restored row it can be diffed by.
        assert [a["kind"] for a in s0["audit"]] == ["generate", "generate", "restore"]
        assert s0["audit"][-1]["before"] == "A new [1]."
        assert s0["audit"][-1]["after"] == "A [1]."
        # Every source the brief ever registered stays.
        assert [s["chunkId"] for s in restored["sources"]] == ["c0", "c1", "c9"]

    def test_restored_brief_keeps_its_own_activity_id(self):
        content = brief_with("A [1].")
        content["activityId"] = "keep-me"
        version = bv.snapshot(content)
        version["activityId"] = "old"
        assert bv.restore_brief(content, version, 1)["activityId"] == "keep-me"


# ---------------------------------------------------------------------------
# The store, with a faked session
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


class VersionSession:
    """Holds brief_versions rows in memory; answers the store's queries."""

    def __init__(self):
        self.rows = []

    async def execute(self, statement):
        text = str(statement)
        params = statement.compile().params
        rows = []
        if "FROM brief_versions" in text:
            rows = sorted(self.rows, key=lambda r: -r.number)
            wanted = [v for k, v in params.items() if k.startswith("number")]
            if wanted:
                rows = [r for r in rows if r.number == wanted[0]]
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(
                first=lambda: rows[0] if rows else None,
                unique=lambda: SimpleNamespace(all=lambda: []),
            ),
            all=lambda: rows,
        )

    def add(self, row):
        self.rows.append(row)

    async def delete(self, row):
        self.rows.remove(row)


def fake_brief(content):
    return SimpleNamespace(
        id=uuid.uuid4(), user_id="owner", content=content, updated_at=NOW
    )


async def save(session, brief, new_content, user="owner", change=None, at=NOW):
    previous = brief.content
    brief.content = new_content
    return await store.record_version(session, brief, previous, user, change, at)


class TestStore:
    @pytest.mark.asyncio
    async def test_first_change_to_an_old_brief_keeps_it_as_version_one(self):
        session = VersionSession()
        brief = fake_brief(brief_with("A [1]."))
        changed = copy.deepcopy(brief.content)
        bc.record_run(changed, "s0", {"mode": "manual", "content": "A2 [1]."})
        await save(session, brief, changed, change=store.VersionChange("manual", "s0"))
        assert [(r.number, r.kind) for r in session.rows] == [
            (1, "baseline"),
            (2, "manual"),
        ]
        assert session.rows[1].summary == "Edited “T0” by hand"

    @pytest.mark.asyncio
    async def test_a_save_that_changes_nothing_writes_no_version(self):
        session = VersionSession()
        brief = fake_brief(brief_with("A [1]."))
        await save(session, brief, copy.deepcopy(brief.content))
        assert session.rows == []
        await store.record_version(
            session, brief, None, "owner", store.VersionChange("created"), NOW
        )
        same = copy.deepcopy(brief.content)
        same["date"] = 99
        await save(session, brief, same, at=NOW + timedelta(seconds=5))
        assert len(session.rows) == 1

    @pytest.mark.asyncio
    async def test_typing_saves_merge_within_the_window_then_split(self):
        session = VersionSession()
        brief = fake_brief(brief_with("A [1].", "B [1]."))
        await store.record_version(
            session, brief, None, "owner", store.VersionChange("created"), NOW
        )
        for minute, title in ((1, "One"), (3, "Two")):
            renamed = copy.deepcopy(brief.content)
            renamed["sections"][0]["title"] = title
            await save(session, brief, renamed, at=NOW + timedelta(minutes=minute))
        assert [r.number for r in session.rows] == [1, 2]
        assert session.rows[1].summary == "Renamed “T0” to “Two”"
        later = copy.deepcopy(brief.content)
        later["sections"][1]["title"] = "Three"
        await save(session, brief, later, at=NOW + timedelta(minutes=20))
        assert [r.number for r in session.rows] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_ai_runs_and_other_people_never_merge(self):
        session = VersionSession()
        brief = fake_brief(brief_with("A [1]."))
        await store.record_version(
            session, brief, None, "owner", store.VersionChange("created"), NOW
        )
        renamed = copy.deepcopy(brief.content)
        renamed["title"] = "X"
        await save(session, brief, renamed, at=NOW + timedelta(minutes=1))
        rerun = copy.deepcopy(brief.content)
        bc.record_run(
            rerun,
            "s0",
            {"mode": "generate", "content": "Again [1].", "sources": [src(1, "c0")]},
        )
        await save(
            session,
            brief,
            rerun,
            change=store.VersionChange("generate", "s0"),
            at=NOW + timedelta(minutes=2),
        )
        assert [r.kind for r in session.rows] == ["created", "settings", "generate"]

    @pytest.mark.asyncio
    async def test_typing_that_undoes_the_latest_version_removes_it(self):
        session = VersionSession()
        brief = fake_brief(brief_with("A [1]."))
        await store.record_version(
            session, brief, None, "owner", store.VersionChange("created"), NOW
        )
        original = copy.deepcopy(brief.content)
        renamed = copy.deepcopy(original)
        renamed["title"] = "X"
        await save(session, brief, renamed, at=NOW + timedelta(minutes=1))
        await save(session, brief, original, at=NOW + timedelta(minutes=2))
        assert [r.number for r in session.rows] == [1]

    def test_merge_window_setting(self, monkeypatch):
        import pipeline.db.config as config

        monkeypatch.setattr(
            config,
            "get_application_config",
            lambda: {"brief": {"versions": {"merge_minutes": 0}}},
        )
        assert store.merge_window() == timedelta(0)
        monkeypatch.setattr(config, "get_application_config", lambda: {})
        assert store.merge_window() == timedelta(minutes=5)
        monkeypatch.setattr(
            config,
            "get_application_config",
            lambda: {"brief": {"versions": {"merge_minutes": "soon"}}},
        )
        with pytest.raises(ValueError, match="merge_minutes"):
            store.merge_window()
