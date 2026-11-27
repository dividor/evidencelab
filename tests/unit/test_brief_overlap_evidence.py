"""Verified passages must refer to the sections that were saved for this run."""

import pytest
from pydantic import ValidationError

from ui.backend.services.brief_experiment_overlap import (
    OverlapVerdict,
    link_saved_repetitions,
)

pytestmark = pytest.mark.unit

DRAFT = {
    "summary": "Duration fell. Costs rose.",
    "siblings": [
        {"title": "Outcomes", "content": "Expenses grew."},
        {"title": "Outcomes", "content": "Time declined."},
    ],
}


def test_each_repetition_keeps_its_own_assessment_and_verified_source():
    verdict = OverlapVerdict.model_validate(
        {
            "reason": "Two findings recur.",
            "repeats": [
                {
                    "other_heading": "Outcomes",
                    "new_clause": "Duration fell.",
                    "existing_clause": "Time declined.",
                    "assessment": "Both describe shorter times.",
                },
                {
                    "other_heading": "Outcomes",
                    "new_clause": "Costs rose.",
                    "existing_clause": "Expenses grew.",
                    "assessment": "Both describe higher costs.",
                },
            ],
        },
        context=DRAFT,
    )
    evidence = [pair.evidence(DRAFT) for pair in verdict.repeats]
    assert [pair["source_index"] for pair in evidence] == [1, 0]
    assert evidence[1]["assessment"] == "Both describe higher costs."
    assert verdict.score == 0
    with pytest.raises(ValidationError):
        OverlapVerdict.model_validate(
            verdict.model_dump(), context={**DRAFT, "summary": ""}
        )


def test_historical_pairs_are_verified_and_keep_the_original_overall_assessment():
    message = (
        "Two trends. “Duration fell.” repeats “Time declined.” in Outcomes. "
        "“Costs rose.” repeats “Expenses grew.” in Outcomes."
    )
    check = {"type": "brief_overlap", "message": message}
    [read] = link_saved_repetitions([check], DRAFT)
    assert read["section_assessment"] == "Two trends."
    assert [p["source_index"] for p in read["repetitions"]] == [1, 0]
    assert all("assessment" not in p for p in read["repetitions"])
    [unverified] = link_saved_repetitions([check], {**DRAFT, "summary": "Unrelated."})
    assert unverified["repetitions"] == [] and unverified["message"] == message
    assert link_saved_repetitions([read], DRAFT) == [read]
