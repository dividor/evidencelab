"""Tests for scripts/ci/review_comment.py: the docs check's comment and pass/fail."""

import json
import subprocess

import pytest

import scripts.ci.review_comment as rc

pytestmark = pytest.mark.unit

SHA = "3db0bba" + "0" * 33
RUN_URL = "https://github.com/o/r/actions/runs/1"
ENV = {"REPO": "o/r", "PR": "7", "SHA": SHA, "RUN_URL": RUN_URL}


def _verdict(**overrides):
    verdict = {
        "needs_docs": True,
        "covered": False,
        "reason": "Adds AI_DAILY_COST_LIMIT_USD; no page describes it.",
        "missing": [
            {"what": "What the limit does", "where": "docs/admin/system-monitoring.md"}
        ],
        "notes": ["A screenshot on search.md shows the old screen."],
    }
    verdict.update(overrides)
    return verdict


class FakeGh:
    """Stands in for subprocess.run of the gh CLI; records each call."""

    def __init__(self, comments=None, fail=False):
        self.comments = comments or []
        self.calls = []
        self.fail = fail

    def __call__(self, args, input=None, capture_output=True, text=True, check=False):
        self.calls.append((args, input))
        if self.fail:
            return subprocess.CompletedProcess(args, 1, "", "HTTP 403")
        if "--paginate" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps([self.comments]), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")


class TestParseVerdict:
    def test_parse_verdict_when_complete_then_returns_it(self):
        assert rc.parse_verdict(json.dumps(_verdict()), rc.DOCS_FIELDS) == _verdict()

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_parse_verdict_when_empty_then_refuses(self, raw):
        with pytest.raises(ValueError, match="no verdict"):
            rc.parse_verdict(raw, rc.DOCS_FIELDS)

    def test_parse_verdict_when_not_json_then_refuses(self):
        with pytest.raises(ValueError, match="not JSON"):
            rc.parse_verdict("needs docs", rc.DOCS_FIELDS)

    def test_parse_verdict_when_not_an_object_then_refuses(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            rc.parse_verdict("[true]", rc.DOCS_FIELDS)

    def test_parse_verdict_when_fields_missing_then_names_them(self):
        partial = {"needs_docs": True, "covered": False, "reason": "x"}
        with pytest.raises(ValueError, match="lacks missing, notes"):
            rc.parse_verdict(json.dumps(partial), rc.DOCS_FIELDS)


class TestDocsFailed:
    @pytest.mark.parametrize(
        ("needs_docs", "covered", "failed"),
        [
            (True, False, True),
            (True, True, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_docs_failed_when_combination_then_fails_only_on_missing_docs(
        self, needs_docs, covered, failed
    ):
        assert (
            rc.docs_failed(_verdict(needs_docs=needs_docs, covered=covered)) is failed
        )


class TestDocsComment:
    def test_docs_comment_when_missing_then_lists_each_gap_and_note(self):
        body = rc.docs_comment(_verdict(), SHA, RUN_URL)

        assert body.startswith(rc.DOCS_MARKER + "\n")
        assert "### Docs check failed: docs are missing" in body
        assert "Adds AI_DAILY_COST_LIMIT_USD" in body
        assert "- **docs/admin/system-monitoring.md**: What the limit does" in body
        assert "**Worth a look** (doesn't block)" in body
        assert "Commit 3db0bba" in body
        assert f"[Run]({RUN_URL})" in body

    def test_docs_comment_when_no_docs_needed_then_says_so_without_lists(self):
        body = rc.docs_comment(
            _verdict(needs_docs=False, covered=True, missing=[], notes=[]), SHA, RUN_URL
        )

        assert "### Docs check passed: no docs needed" in body
        assert "Missing from" not in body
        assert "Worth a look" not in body

    def test_docs_comment_when_covered_then_passes(self):
        body = rc.docs_comment(_verdict(covered=True, missing=[]), SHA, RUN_URL)

        assert "### Docs check passed: the docs are included" in body


class TestFindCommentId:
    def test_find_comment_id_when_own_comment_on_a_later_page_then_finds_it(self):
        pages = [
            [{"id": 1, "user": {"login": "someone"}, "body": "looks good"}],
            [
                {
                    "id": 2,
                    "user": {"login": rc.COMMENT_AUTHOR},
                    "body": rc.DOCS_MARKER + "\nx",
                }
            ],
        ]

        assert rc.find_comment_id(pages, rc.DOCS_MARKER) == 2

    def test_find_comment_id_when_marker_quoted_by_someone_else_then_ignores_it(self):
        pages = [[{"id": 3, "user": {"login": "someone"}, "body": rc.DOCS_MARKER}]]

        assert rc.find_comment_id(pages, rc.DOCS_MARKER) is None

    def test_find_comment_id_when_bot_comment_without_marker_then_ignores_it(self):
        pages = [
            [{"id": 4, "user": {"login": rc.COMMENT_AUTHOR}, "body": "other check"}]
        ]

        assert rc.find_comment_id(pages, rc.DOCS_MARKER) is None


class TestUpsertComment:
    def test_upsert_comment_when_none_yet_then_adds_one(self):
        gh = FakeGh()

        rc.upsert_comment("o/r", "7", rc.DOCS_MARKER, "body", run=gh)

        args, payload = gh.calls[-1]
        assert args == [
            "gh",
            "api",
            "-X",
            "POST",
            "repos/o/r/issues/7/comments",
            "--input",
            "-",
        ]
        assert json.loads(payload) == {"body": "body"}

    def test_upsert_comment_when_one_exists_then_updates_it(self):
        own = {"id": 99, "user": {"login": rc.COMMENT_AUTHOR}, "body": rc.DOCS_MARKER}
        gh = FakeGh(comments=[own])

        rc.upsert_comment("o/r", "7", rc.DOCS_MARKER, "new body", run=gh)

        args, payload = gh.calls[-1]
        assert args == [
            "gh",
            "api",
            "-X",
            "PATCH",
            "repos/o/r/issues/comments/99",
            "--input",
            "-",
        ]
        assert json.loads(payload) == {"body": "new body"}

    def test_upsert_comment_when_gh_fails_then_raises(self):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            rc.upsert_comment("o/r", "7", rc.DOCS_MARKER, "body", run=FakeGh(fail=True))


class TestRunDocs:
    def test_run_docs_when_docs_missing_then_comments_and_fails(self):
        gh = FakeGh()

        code = rc.run_docs({**ENV, "VERDICT": json.dumps(_verdict())}, run=gh)

        assert code == 1
        assert "docs are missing" in json.loads(gh.calls[-1][1])["body"]

    def test_run_docs_when_covered_then_comments_and_passes(self):
        gh = FakeGh()

        code = rc.run_docs(
            {**ENV, "VERDICT": json.dumps(_verdict(covered=True))}, run=gh
        )

        assert code == 0
        assert "the docs are included" in json.loads(gh.calls[-1][1])["body"]

    def test_run_docs_when_no_verdict_then_comments_and_fails(self):
        gh = FakeGh()

        code = rc.run_docs({**ENV, "VERDICT": ""}, run=gh)

        assert code == 1
        body = json.loads(gh.calls[-1][1])["body"]
        assert body.startswith(rc.DOCS_MARKER)
        assert "### Docs check failed: no verdict" in body
        assert "the check gave no verdict" in body


class TestMain:
    @pytest.mark.parametrize("argv", [[], ["lint"], ["docs", "ux"]])
    def test_main_when_unknown_command_then_usage(self, capsys, argv):
        assert rc.main(argv) == 2
        assert "usage" in capsys.readouterr().err

    def test_main_when_docs_then_reads_the_environment(self, monkeypatch):
        seen = {}
        monkeypatch.setitem(rc.COMMANDS, "docs", lambda env: seen.update(env) or 0)
        for name, value in {**ENV, "VERDICT": "{}"}.items():
            monkeypatch.setenv(name, value)

        assert rc.main(["docs"]) == 0
        assert seen["PR"] == "7" and seen["VERDICT"] == "{}"
