"""Summarise the recorded section and factual claim grades without judging again."""

from ui.backend.services.brief_experiment_claims import is_factual_criterion
from ui.backend.services.evaluation_metrics import outcome_stats


def _graded_claims(assertions):
    factual = next((a for a in assertions if is_factual_criterion(a)), {})
    return (
        g
        for g in factual.get("claim_grades") or []
        if not g.get("error")
        and g.get("factual") is not False
        and g.get("score") is not None
        and isinstance(g.get("passed"), bool)
    )


def factual_claim_metrics(results):
    scores = [
        g for row in results for g in _graded_claims(row.get("assertion_results") or [])
    ]
    count = len(scores)
    return {
        "factual_claim_mean_score": (
            round(sum(g["score"] for g in scores) / count, 4) if count else None
        ),
        "factual_claim_pass_rate": (
            round(sum(g["passed"] for g in scores) / count, 4) if count else None
        ),
    }


def section_total_score(section):
    if section["status"] == "error":
        return None
    return min(
        (
            c["score"]
            for c in section["assertion_results"]
            if c.get("score") is not None
        ),
        default=None,
    )


def saved_brief_scores(sections):
    outcomes = [
        dict(status=s["status"], score=section_total_score(s)) for s in sections
    ]
    stats = outcome_stats(outcomes)
    return {
        "mean_score": stats["mean_score"],
        "pass_rate": stats["pass_rate"],
        **factual_claim_metrics(sections),
    }
