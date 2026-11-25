"""Tests for scripts/ci/review_comment.py: the UX review's comment and check."""

import json
import subprocess

import pytest

import scripts.ci.review_comment as rc

pytestmark = pytest.mark.unit

SHA = "3db0bba" + "0" * 33
RUN_URL = "https://github.com/o/r/actions/runs/1"
ENV = {"REPO": "o/r", "PR": "7", "SHA": SHA, "RUN_URL": RUN_URL}


class FakeApi:
    """Stands in for subprocess.run of the GitHub CLI; records each call."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, input=None, capture_output=True, text=True, check=False):
        self.calls.append((args, input))
        if "--paginate" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps([[]]), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")

    def check_runs(self):
        return [
            json.loads(body)
            for args, body in self.calls
            if "repos/o/r/check-runs" in args
        ]

    def comments(self):
        return [
            json.loads(body)["body"]
            for args, body in self.calls
            if "repos/o/r/issues/7/comments" in args and body
        ]


def _ux(**overrides):
    verdict = {
        "verdict": "needs changes",
        "summary": "The filter panel runs off the right edge on a phone.",
        "screens": ["Search results, 390×844", "Search results, 1440×900"],
        "findings": [
            {
                "severity": "must fix",
                "where": "Search results, 390×844, search-390.png",
                "what": "Filter panel is 420 px wide | page scrolls sideways",
                "fix": "Let .filters wrap\nbelow 640 px",
            }
        ],
    }
    verdict.update(overrides)
    return verdict


class TestUxVerdict:
    @pytest.mark.parametrize(
        ("verdict", "failed"),
        [("looks good", False), ("needs changes", True), ("could not review", True)],
    )
    def test_ux_failed_when_verdict_then_passes_only_when_it_looks_good(
        self, verdict, failed
    ):
        assert rc.ux_failed(_ux(verdict=verdict)) is failed

    def test_table_cell_when_pipes_and_line_breaks_then_one_safe_cell(self):
        assert rc.table_cell("a | b\nc") == "a \\| b c"


class TestUxComment:
    def test_ux_comment_when_findings_then_tabulates_them_and_lists_screens(self):
        body = rc.ux_comment(_ux(), SHA, RUN_URL)

        assert body.startswith(rc.UX_MARKER + "\n")
        assert "### UX review: needs changes" in body
        assert (
            "| must fix | Search results, 390×844, search-390.png | "
            "Filter panel is 420 px wide \\| page scrolls sideways | "
            "Let .filters wrap below 640 px |"
        ) in body
        assert "- Search results, 390×844" in body
        assert "`ux-review-screenshots` artifact" in body

    def test_ux_comment_when_no_findings_then_no_table(self):
        body = rc.ux_comment(_ux(verdict="looks good", findings=[]), SHA, RUN_URL)

        assert "### UX review: looks good" in body
        assert "| Severity |" not in body


class TestRunUx:
    def test_run_ux_when_changes_needed_then_comments_reports_failure_and_exits_0(self):
        api = FakeApi()

        code = rc.run_ux({**ENV, "VERDICT": json.dumps(_ux())}, run=api)

        assert code == 0
        assert api.comments()[0].startswith(rc.UX_MARKER)
        (check,) = api.check_runs()
        assert check["name"] == "UX review"
        assert check["head_sha"] == SHA
        assert check["status"] == "completed"
        assert check["conclusion"] == "failure"
        assert check["output"]["title"] == "UX review: needs changes"

    def test_run_ux_when_it_looks_good_then_reports_success(self):
        api = FakeApi()
        verdict = _ux(verdict="looks good", findings=[])

        rc.run_ux({**ENV, "VERDICT": json.dumps(verdict)}, run=api)

        assert api.check_runs()[0]["conclusion"] == "success"

    def test_run_ux_when_review_step_skipped_then_says_so(self):
        api = FakeApi()

        rc.run_ux({**ENV, "VERDICT": "", "REVIEW_OUTCOME": "skipped"}, run=api)

        summary = api.check_runs()[0]["output"]["summary"]
        assert (
            "the check gave no verdict (the review step's outcome was skipped)"
            in summary
        )

    def test_run_ux_when_no_verdict_then_reports_failure_and_exits_0(self):
        api = FakeApi()

        code = rc.run_ux({**ENV, "VERDICT": ""}, run=api)

        assert code == 0
        (check,) = api.check_runs()
        assert check["conclusion"] == "failure"
        assert check["output"]["title"] == "No verdict"
        assert "### UX review failed: no verdict" in check["output"]["summary"]

    def test_report_check_when_summary_too_long_then_cut_to_githubs_limit(self):
        api = FakeApi()

        rc.report_check(
            "o/r", SHA, False, "t", "x" * (rc.CHECK_SUMMARY_LIMIT + 10), run=api
        )

        assert len(api.check_runs()[0]["output"]["summary"]) == rc.CHECK_SUMMARY_LIMIT


class TestMainUx:
    def test_main_when_ux_then_runs_the_review(self, monkeypatch):
        monkeypatch.setitem(rc.COMMANDS, "ux", lambda env: 0)
        for name, value in ENV.items():
            monkeypatch.setenv(name, value)

        assert rc.main(["ux"]) == 0
