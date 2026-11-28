"""Aggregate per-case evaluation results into experiment summary statistics.

Kept as a tiny dependency-free module so the stats math is unit-testable
without importing the live run engine (which pulls in search/LLM services).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from ui.backend.services.job_liveness import progress_stats as liveness_progress

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_ERROR = "error"


def _sum_token_usage(case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum per-case LLM usage into run totals.

    Cost is JSON-safe (float, 6 decimals) because the totals live in the
    ``summary_stats`` JSONB column; None when no case reported a cost.
    """
    prompt = sum(int(r.get("prompt_tokens") or 0) for r in case_results)
    completion = sum(int(r.get("completion_tokens") or 0) for r in case_results)
    costs = [r["cost_usd"] for r in case_results if r.get("cost_usd") is not None]
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost_usd": round(float(sum(float(c) for c in costs)), 6) if costs else None,
    }


def compute_summary_stats(
    case_results: List[Dict[str, Any]], duration_ms: int
) -> Dict[str, Any]:
    """Roll up per-case outcomes into counts, pass_rate, mean_score, duration,
    and total LLM token usage / cost.

    ``pass_rate`` is a fraction in [0, 1]; ``mean_score`` averages only the
    non-null case scores (None when no case produced a score). All numbers are
    labelled with units by the UI (``ms``, ``%``, counts).
    """
    return {
        **outcome_stats(case_results),
        "duration_ms": duration_ms,
        **_sum_token_usage(case_results),
    }


def outcome_stats(case_results):
    """Count every outcome in the pass rate and only scored outcomes in the mean."""
    total = len(case_results)
    passed = sum(1 for r in case_results if r.get("status") == RESULT_PASS)
    failed = sum(1 for r in case_results if r.get("status") == RESULT_FAIL)
    errored = sum(1 for r in case_results if r.get("status") == RESULT_ERROR)
    scores = [r["score"] for r in case_results if r.get("score") is not None]
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
    }


def progress_stats(
    completed: int, total: int, sections=None, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """A lightweight progress marker stored in a run's or check's
    ``summary_stats`` while it is in flight, so the polling UI can show
    "completed of total" and, when ``sections`` is given, the work still to
    do. Its ``at`` stamp is the job's heartbeat (``job_liveness``).

    It is replaced by the real aggregate stats (``compute_summary_stats``) once
    the run finishes, so a running run never carries pass/score numbers.
    """
    stats = liveness_progress(completed, total, now)
    if sections is not None:
        stats["progress"]["remaining_sections"] = sections[completed:]
    return stats
