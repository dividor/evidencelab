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
