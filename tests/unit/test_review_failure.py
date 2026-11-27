"""Tests for the review action's failure diagnostics."""

import json

import pytest

from scripts.ci.review_failure import report_failure, summarize_failure

pytestmark = pytest.mark.unit


def test_summarize_failure_when_api_credits_are_exhausted_then_prints_safe_reason():
    result = {
        "type": "result",
        "is_error": True,
        "api_error_status": 400,
        "result": "Credit balance is too low. This response contains internal details.",
    }
    assert summarize_failure([result]) == (
        "Review API returned HTTP 400. API credits are exhausted."
    )


def test_summarize_failure_when_reason_is_unknown_then_omits_raw_text():
    result = {
        "type": "result",
        "is_error": True,
        "api_error_status": 403,
        "errors": ["Private provider response"],
    }
    assert summarize_failure([result]) == (
        "Review API returned HTTP 403. The SDK gave no recognized error reason."
    )


def test_report_failure_when_log_is_present_then_reads_the_failed_result(tmp_path):
    execution_file = tmp_path / "review.json"
    execution_file.write_text(
        json.dumps(
            [{"type": "result", "is_error": True, "errors": ["Rate limit exceeded"]}]
        ),
        encoding="utf-8",
    )
    assert report_failure(tmp_path, str(execution_file)) == (
        "Review execution failed. API rate limit reached."
    )


def test_report_failure_when_log_is_outside_runner_temp_then_does_not_read_it(tmp_path):
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    execution_file = tmp_path / "outside.json"
    execution_file.write_text("This would fail JSON parsing if read.", encoding="utf-8")
    assert report_failure(runner_temp, str(execution_file)) == (
        "The review action provided no execution log in the runner's temp directory."
    )


def test_summarize_failure_when_sdk_did_not_fail_then_reports_no_failed_result():
    assert summarize_failure([{"type": "result", "is_error": False}]) == (
        "The execution log contains no failed SDK result."
    )
