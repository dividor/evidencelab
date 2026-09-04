"""Unit tests for evaluation-harness summary-stat aggregation."""

import pytest

from ui.backend.services.evaluation_metrics import compute_summary_stats

pytestmark = pytest.mark.unit


def test_compute_summary_stats_mixed_then_counts_and_rates():
    results = [
        {"status": "pass", "score": 1.0},
        {"status": "fail", "score": 0.0},
        {"status": "error", "score": None},
        {"status": "pass", "score": 0.8},
    ]
    stats = compute_summary_stats(results, 500)
    assert stats["total"] == 4
    assert stats["passed"] == 2 and stats["failed"] == 1 and stats["errored"] == 1
    assert stats["pass_rate"] == 0.5
    assert stats["mean_score"] == 0.6  # mean of [1.0, 0.0, 0.8], errors excluded
    assert stats["duration_ms"] == 500


def test_compute_summary_stats_empty_then_safe_defaults():
    stats = compute_summary_stats([], 0)
    assert stats["total"] == 0
    assert stats["pass_rate"] == 0.0
    assert stats["mean_score"] is None


def test_compute_summary_stats_all_pass_then_full_rate():
    stats = compute_summary_stats([{"status": "pass", "score": 1.0}] * 3, 10)
    assert stats["pass_rate"] == 1.0 and stats["mean_score"] == 1.0


def test_compute_summary_stats_sums_token_usage_and_cost():
    results = [
        {
            "status": "pass",
            "score": 1.0,
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "cost_usd": 0.00072,
        },
        {
            "status": "fail",
            "score": 0.0,
            "prompt_tokens": 500,
            "completion_tokens": 100,
            "cost_usd": 0.00036,
        },
        # Errored case with no LLM usage at all.
        {"status": "error", "score": None},
    ]
    stats = compute_summary_stats(results, 100)
    assert stats["prompt_tokens"] == 1500
    assert stats["completion_tokens"] == 300
    assert stats["total_tokens"] == 1800
    assert stats["cost_usd"] == pytest.approx(0.00108)


def test_compute_summary_stats_when_no_usage_then_zero_tokens_null_cost():
    stats = compute_summary_stats([{"status": "pass", "score": 1.0}], 10)
    assert stats["prompt_tokens"] == 0
    assert stats["completion_tokens"] == 0
    assert stats["total_tokens"] == 0
    assert stats["cost_usd"] is None
