"""Run and section metrics use the same graded factual claims on both screens."""

import pytest

from ui.backend.services.brief_score_metrics import (
    factual_claim_metrics,
    saved_brief_scores,
)

pytestmark = pytest.mark.unit


def section(status, total, grades):
    return dict(
        status=status,
        assertion_results=[
            dict(type="brief_structure", score=total),
            dict(type="brief_factual", claim_grades=grades),
            dict(
                type="llm_judge",
                rubric="A different criterion.",
                claim_grades=[dict(score=0, passed=False)],
            ),
        ],
    )


def test_weighted_claim_scores_include_partial_grades_from_errored_sections():
    first = section("pass", 0.9, [dict(score=0.9, passed=True, factual=True)])
    second = section(
        "error",
        0,
        [
            dict(score=0, passed=False),
            dict(score=0.3, passed=False),
            dict(score=1, passed=True),
            dict(score=1, passed=True, factual=False),
            dict(error=True),
            dict(score=None),
        ],
    )
    assert factual_claim_metrics([first]) == dict(
        factual_claim_mean_score=0.9, factual_claim_pass_rate=1
    )
    assert saved_brief_scores([first, second]) == dict(
        pass_rate=0.5,
        mean_score=0.9,
        factual_claim_mean_score=0.55,
        factual_claim_pass_rate=0.5,
    )


def test_no_individual_grades_is_unavailable_even_when_the_section_has_a_score():
    result = section("fail", 0, [])
    assert saved_brief_scores([result]) == dict(
        pass_rate=0,
        mean_score=0,
        factual_claim_mean_score=None,
        factual_claim_pass_rate=None,
    )
