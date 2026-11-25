"""Tests for scripts/ci/saved_brief.py: the saved brief the layout checks open."""

import json
import re
from unittest.mock import MagicMock, patch

import pytest

import scripts.ci.saved_brief as sb

pytestmark = pytest.mark.unit

MARKER = re.compile(r"\[(\d+)\]")


class FakeApi:
    """Stands in for POST /brief/citations: records each operation, echoes content."""

    def __init__(self):
        self.ops = []

    def __call__(self, body):
        self.ops.append(body["op"])
        content = dict(body["content"])
        content["applied"] = len(self.ops)
        return {"content": content, "read": {}}


class TestBuildSavedBrief:
    def test_build_when_called_then_sends_structure_then_one_run_per_section(self):
        api = FakeApi()

        content = sb.build_saved_brief(api, now_ms=1_700_000_000_000)

        assert [op["type"] for op in api.ops] == ["structure"] + ["run"] * len(
            sb.SECTIONS
        )
        assert [op["sectionId"] for op in api.ops[1:]] == [s["id"] for s in sb.SECTIONS]
        assert content["applied"] == len(sb.SECTIONS) + 1

    def test_structure_when_built_then_lists_every_section_as_done(self):
        structure = sb.brief_structure(1_700_000_000_000)

        assert structure["id"] == sb.BRIEF_ID
        assert structure["title"] == sb.BRIEF_TITLE
        assert structure["citationsVersion"] == sb.CITATIONS_VERSION
        assert [s["status"] for s in structure["sections"]] == ["done"] * len(
            sb.SECTIONS
        )
        assert structure["sectionCount"] == len(sb.SECTIONS)

    @pytest.mark.parametrize("section", sb.SECTIONS, ids=lambda s: s["id"])
    def test_run_body_when_built_then_numbers_its_sources_from_one(self, section):
        body = sb.run_body(section)

        assert body["mode"] == "generate"
        assert [src["index"] for src in body["sources"]] == list(
            range(1, len(section["sources"]) + 1)
        )
        assert all(src["chunkId"] for src in body["sources"])

    def test_sections_when_read_then_exactly_one_citation_has_no_source(self):
        unmatched = [
            (s["id"], int(n))
            for s in sb.SECTIONS
            for n in MARKER.findall(s["content"])
            if int(n) > len(s["sources"])
        ]

        assert unmatched == [("ux-cost", 9)]


class TestLocalStorageScript:
    def test_script_when_built_then_stores_the_brief_as_the_only_saved_one(self):
        script = sb.local_storage_script({"id": sb.BRIEF_ID, "title": "T"})

        match = re.fullmatch(r'localStorage\.setItem\("([^"]+)", (".*")\);', script)
        assert match and match.group(1) == sb.BRIEF_HISTORY_KEY
        assert json.loads(json.loads(match.group(2))) == [
            {"id": sb.BRIEF_ID, "title": "T"}
        ]


class TestApiPoster:
    def test_poster_when_called_then_posts_with_the_key_and_returns_json(self):
        response = MagicMock()
        response.json.return_value = {"content": {"ok": True}}
        with patch.object(sb.requests, "post", return_value=response) as post:
            result = sb.api_poster("http://api:8000/", "key-1")(
                {"op": {"type": "read"}}
            )

        post.assert_called_once_with(
            "http://api:8000/brief/citations",
            json={"op": {"type": "read"}},
            headers={"X-API-Key": "key-1"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once()
        assert result == {"content": {"ok": True}}
