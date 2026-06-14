"""Aggregate per-case evaluation results into experiment summary statistics.

Kept as a tiny dependency-free module so the stats math is unit-testable
without importing the live run engine (which pulls in search/LLM services).
"""

from typing import Any, Dict, List

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_ERROR = "error"


def compute_summary_stats(
    case_results: List[Dict[str, Any]], duration_ms: int
) -> Dict[str, Any]:
    """Roll up per-case outcomes into counts, pass_rate, mean_score, duration.

    ``pass_rate`` is a fraction in [0, 1]; ``mean_score`` averages only the
    non-null case scores (None when no case produced a score). All numbers are
    labelled with units by the UI (``ms``, ``%``, counts).
    """
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
        "duration_ms": duration_ms,
    }
