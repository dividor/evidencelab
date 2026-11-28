"""Verify the last length edit preserves reviewed text and its evidence."""

from unittest.mock import AsyncMock

import pytest

from ui.backend.services.assistant_brief_writer import (
    FindingScopeAssessment,
    _brief_draft_text,
    _sourced_scope_revision,
    develop_short_brief,
)
from ui.backend.services.assistant_grounding import EvidenceQuote
from ui.backend.services.brief_repetition import RepeatedSentence
from ui.backend.services.citation_fidelity import match_key

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, 10])
async def test_section_with_no_missing_length_skips_another_edit(target):
    draft = "The valve was closed before the overnight pressure test [1]."
    write, review = AsyncMock(), AsyncMock()
    assert (
        await develop_short_brief(draft, target, {}, write, review, retrieved=[])
        == draft
    )
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
    result = await develop_short_brief(draft, 14, {}, write, review, retrieved=[])
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


@pytest.mark.parametrize("labels", [[], [3], [1, 3], [2]])
def test_scope_edit_requires_original_source_labels_and_a_verified_quote(labels):
    row = {"text": "A mixed finding [1, 2].", "citations": [1, 2]}
    review = FindingScopeAssessment(
        subject="Test",
        reason="Narrow the finding",
        keep=False,
        source_matches_assignment=True,
        unsupported_phrases=["always"],
        covers_other_heading=False,
        in_scope_revision="The device ran",
        revision_citations=labels,
    )
    quotes = {row["text"]: [EvidenceQuote(citation=1, quote="The device ran.")]}
    assert _sourced_scope_revision(review, row, quotes) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("labels", "expected"),
    [([1, 4, 4, 7, 8], [4, 7]), ([1, 2], [1, 2]), ([1, 4], [4, 1])],
)
async def test_final_edit_selects_unused_passages_within_the_original_budget(
    labels, expected
):
    def passage(label):
        return {"global_index": label, "text": f"Passage {label}."}

    original = {label: passage(label) for label in [1, 2]}
    write = AsyncMock(return_value="")
    draft = "An inspection took place [1, 2]."
    retrieved = [{"global_index": 9, "text": " "}, *(passage(i) for i in labels)]
    result = await develop_short_brief(
        draft, 100, original, write, AsyncMock(), retrieved=retrieved
    )
    assert result == draft
    assert list(write.await_args.kwargs["evidence"]) == expected
    assert write.await_args.kwargs["continuation"] == draft
