"""Unit tests for the legacy-brief conversion and its browser comparison."""

import json
import uuid

import pytest

from ui.backend.services import brief_citations as bc
from ui.backend.services import brief_citations_convert as conv

pytestmark = pytest.mark.unit


def legacy_source(index, chunk, doc="d1", page=None, **extra):
    return {
        "chunkId": chunk,
        "docId": doc,
        "title": f"Doc {doc}",
        "text": f"Excerpt {chunk}",
        "score": 0.1,
        "page": page,
        "index": index,
        **extra,
    }


LEGACY = {
    "id": "b1",
    "title": "Legacy brief",
    "date": 1700000000000,
    "sectionCount": 3,
    "sourceCount": 5,
    "activityId": "act-1",
    "sections": [
        {
            "id": "a",
            "title": "First",
            "level": 1,
            "status": "done",
            "content": "# First\n\nOne [1]. Two [2]. Gone [9].",
            "sources": [
                legacy_source(
                    1, "c1", page=3, claimMatches=[{"claim": "one", "matches": []}]
                ),
                legacy_source(2, "c2", page=5),
                legacy_source(3, "", doc="d7"),
            ],
            "audit": [{"id": "x", "kind": "generate", "at": 1, "question": "First"}],
            "lastResearchedAt": 1700000001000,
        },
        {
            "id": "b",
            "title": "Second",
            "level": 1,
            "status": "pending",
            "content": "",
            "sources": [],
        },
        {
            "id": "c",
            "title": "Third",
            "level": 2,
            "status": "done",
            "content": "Again [1].",
            "sources": [legacy_source(1, "c2", page=5)],
        },
    ],
}


class TestConvert:
    def test_converts_sections_into_runs_and_renumbers(self):
        content, report = conv.convert_legacy(LEGACY, now_ms=5)
        assert content["citationsVersion"] == 2
        assert content["referenceGrouping"] == "passage"
        assert content["activityId"] == "act-1"
        a = bc.find_section(content, "a")
        assert a["runs"][0]["content"] == LEGACY["sections"][0]["content"]
        assert a["runs"][0]["at"] == 1700000001000
        assert a["renumbered"]["content"] == "One [1]. Two [2]. Gone [?9]."
        assert bc.find_section(content, "c")["renumbered"]["content"] == "Again [2]."
        assert bc.find_section(content, "b")["status"] == "pending"
        assert [(r["n"], r["page"]) for r in content["references"]] == [(1, 3), (2, 5)]
        assert "content" not in a and "sources" not in a

    def test_report_counts(self):
        _, report = conv.convert_legacy(LEGACY)
        assert report["markers"] == 4
        assert report["markersNoSource"] == 1
        assert report["sourcesNoChunkId"] == 1
        assert report["sourcesRegistered"] == 2
        assert [s["unresolved"] for s in report["sections"]] == [[9], []]
        assert report["bytesAfter"] > report["bytesBefore"] > 0

    def test_legacy_audit_rows_kept_and_linked(self):
        content, _ = conv.convert_legacy(LEGACY)
        audit = bc.find_section(content, "a")["audit"]
        assert len(audit) == 1 and audit[0]["id"] == "x" and audit[0]["runId"] == "r1"
        assert bc.find_section(content, "c")["audit"][0]["runId"] == "r2"

    def test_highlights_move_to_the_source_list(self):
        content, _ = conv.convert_legacy(LEGACY)
        by_chunk = {s["chunkId"]: s for s in content["sources"]}
        assert by_chunk["c1"]["claimMatches"] == [{"claim": "one", "matches": []}]
        assert "claimMatches" not in by_chunk["c2"]

    def test_already_converted_is_refused(self):
        content, _ = conv.convert_legacy(LEGACY)
        with pytest.raises(ValueError):
            conv.convert_legacy(content)
        assert not conv.is_legacy(content) and conv.is_legacy(LEGACY)


class TestCompare:
    def test_equal_and_same_citations_verdicts(self):
        content, _ = conv.convert_legacy(LEGACY)
        browser = {
            "sections": {
                "a": {
                    "content": "One [1]. Two [2]. Gone .",
                    "sources": [
                        {"index": 1, "chunkId": "c1"},
                        {"index": 2, "chunkId": "c2"},
                    ],
                },
                "c": {
                    "content": "Again [2].",
                    "sources": [{"index": 2, "chunkId": "c2"}],
                },
            },
            "refs": [
                {"n": 1, "chunkId": "c1", "page": 3},
                {"n": 2, "chunkId": "c2", "page": 5},
            ],
        }
        result = conv.compare_with_legacy(content, browser)
        assert result["sections"]["c"] == conv.COMPARE_EQUAL
        # The browser dropped [9]; the API keeps it as [?9]: same citations.
        assert result["sections"]["a"] == conv.COMPARE_SAME_CITATIONS
        assert result["referencesEqual"] is True

    def test_differs_when_a_marker_points_elsewhere(self):
        content, _ = conv.convert_legacy(LEGACY)
        browser = {
            "sections": {
                "c": {
                    "content": "Again [2].",
                    "sources": [{"index": 2, "chunkId": "zzz"}],
                }
            },
            "refs": [],
        }
        result = conv.compare_with_legacy(content, browser)
        assert result["sections"]["c"] == conv.COMPARE_DIFFERS
        assert result["sections"]["a"] == "missing-in-legacy"
        assert result["referencesEqual"] is False


class FakeConn:
    """Answers the Activity row lookup and records the update."""

    def __init__(self, row):
        self.row, self.updates = row, []

    def execute(self, statement, params):
        if str(statement).startswith("SELECT"):
            row = self.row
            return type("R", (), {"fetchone": staticmethod(lambda: row)})()
        self.updates.append(params)
        return None


class TestRefreshActivityRow:
    def test_rewrites_the_row_from_the_converted_content(self):
        content, _ = conv.convert_legacy({**LEGACY, "activityId": str(uuid.uuid4())})
        conn = FakeConn(("row-1", {"timing": {"x": 1}}))
        assert (
            conv.refresh_activity_row(conn, "b1", "u1", "Legacy brief", content) is True
        )
        update = conn.updates[0]
        assert update["id"] == "row-1" and update["query"] == "Legacy brief"
        assert json.loads(update["filters"]) == {
            "timing": {"x": 1},
            "type": "brief",
            "brief_id": "b1",
        }
        assert "One [1]. Two [2]. Gone [?9]." in update["summary"]
        assert [r["n"] for r in json.loads(update["results"])] == [1, 2]

    def test_without_a_row_or_an_activity_id_nothing_is_written(self):
        content, _ = conv.convert_legacy({**LEGACY, "activityId": str(uuid.uuid4())})
        conn = FakeConn(None)
        assert conv.refresh_activity_row(conn, "b1", "u1", "t", content) is False
        assert conn.updates == []
        content["activityId"] = None
        assert (
            conv.refresh_activity_row(FakeConn(("r", {})), "b1", "u1", "t", content)
            is False
        )
