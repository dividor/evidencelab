"""Verify the last length edit preserves reviewed text and its evidence."""

from unittest.mock import AsyncMock

import pytest

from ui.backend.services.assistant_brief_writer import (
    _brief_draft_text,
    develop_short_brief,
)
from ui.backend.services.brief_repetition import RepeatedSentence
from ui.backend.services.citation_fidelity import match_key

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, 10])
async def test_section_with_no_missing_length_skips_another_edit(target):
    draft = "The valve was closed before the overnight pressure test [1]."
    write, review = AsyncMock(), AsyncMock()
    assert await develop_short_brief(draft, target, {}, write, review) == draft
    write.assert_not_awaited()
    review.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("addition", "issues", "accepted"),
    [
        ("", [], False),
        ("The gauges remained stable throughout the test [2].", [], True),
        (
            "The gauges remained stable throughout the test [2].",
            ["Different topic"],
            False,
        ),
        ("An unrelated observation was repeated. " * 10, [], False),
    ],
)
async def test_short_section_keeps_only_an_addition_that_fits_and_reads_well(
    addition, issues, accepted
):
    draft = "The team inspected the valve [1]."
    write, review = AsyncMock(return_value=addition), AsyncMock(return_value=issues)
    result = await develop_short_brief(draft, 14, {}, write, review)
    write.assert_awaited_once_with(evidence={}, target_words=9, continuation=draft)
    assert result == (f"{draft} {addition}" if accepted else draft)
    if addition and len(addition.split()) < 10:
        review.assert_awaited_once_with(f"{draft} {addition}", final=True)
    else:
        review.assert_not_awaited()


def test_review_receives_clean_prose_and_all_sources_from_separately_listed_excerpts():
    evidence = {
        i: {"global_index": i, "text": "Pressure dropped overnight."} for i in (1, 2, 3)
    }
    quotes = {i: (i, "Pressure dropped overnight.") for i in evidence}
    text, issues, _ = _brief_draft_text(
        "Pressure dropped overnight [1], [2], [3].", evidence, set(), quotes
    )
    assert text == "Pressure dropped overnight [1, 2, 3]."
    assert not issues


@pytest.mark.parametrize(
    ("proposed", "previous", "repeated"),
    [
        ("Pressure rose by 12.5 percent", "Pressure rose", False),
        ("Flow rose from 12 to 21 units", "Flow rose to 21 units", False),
        ("The log lists 1,200 entries", "The log lists 1200.0 entries", True),
    ],
)
def test_repetition_requires_previous_text_to_establish_each_reported_figure(
    proposed, previous, repeated
):
    review = RepeatedSentence.model_validate(
        {"id": 1, "pairs": [{"new_clause": proposed, "existing_clause": previous}]}
    )
    assert review.covers(f"{proposed} [7].", [match_key(previous)]) is repeated


def test_conversion_proof_must_quote_the_earlier_amount():
    earlier = "The inspection lasted two days"
    clause = RepeatedSentence.model_validate(
        {
            "id": 1,
            "pairs": [
                {
                    "new_clause": "The inspection took 48 hours",
                    "existing_clause": earlier,
                    "equivalent_amount": "four days",
                }
            ],
        }
    )
    assert not clause.covers("The inspection took 48 hours.", [match_key(earlier)])
