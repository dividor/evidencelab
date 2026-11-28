"""The Brief scope reviewer must fit its response budget without losing context."""

import json

import pytest

from ui.backend.auth.schemas import BriefOutlineSection, BriefSectionPrompt
from ui.backend.services.assistant_brief_writer import _review_finding_scope
from ui.backend.services.assistant_grounding import TruncatedAssistantResponse

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.parametrize("batch_problem", [None, "misassigned", "truncated"])
async def test_long_scope_review_checks_each_id_in_its_batch(batch_problem):
    sentences = [f"Probe {n} recorded a stable signal [1]." for n in range(1, 11)]
    draft = "\n\n".join(" ".join(sentences[n : n + 5]) for n in (0, 5))
    section = BriefSectionPrompt(
        outline=[BriefOutlineSection(title="Probe readings")], current=0
    )
    batches = []

    async def review(system, request, history, config, schema):
        rows = json.loads(request.split("Sentences: ", 1)[1].splitlines()[0])
        batches.append([row["id"] for row in rows])
        assert len(rows) <= 4
        assert json.dumps(draft) in request
        if batch_problem == "truncated" and len(rows) > 1 and rows[0]["id"] == 5:
            raise TruncatedAssistantResponse("The response reached its output limit")
        decisions = []
        for row in reversed(rows):
            index = row["id"]
            if index > 1:
                assert row["preceding_sentence"] == sentences[index - 2]
            decisions.append(
                {
                    "id": 1 if batch_problem == "misassigned" and index == 5 else index,
                    "subject": "Probe readings",
                    "reason": "Review of the recorded measurement",
                    "source_matches_assignment": True,
                    "unsupported_phrases": [],
                    "covers_other_heading": index == 6,
                    "keep": index != 6,
                }
            )
        if "Review the single sentence supplied" in system:
            assert len(rows) == 1
            decisions[0].pop("id")
            return schema.validate_python(decisions[0])
        return schema.validate_python({"reviews": decisions})

    result = _review_finding_scope(
        draft,
        section,
        {1: {"title": "Probe log", "brief_subject_evidence": "Probe readings"}},
        {},
        {},
        "Probes",
        {},
        review,
    )
    text, issues = await result
    expected = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10]]
    if batch_problem:
        expected.extend([[5], [6], [7], [8]])
    assert sorted(batches) == sorted(expected)
    assert text == draft.replace(sentences[5] + " ", "")
    assert len(issues) == 1


async def test_truncated_individual_scope_review_still_reports_an_error():
    draft = "The probe started [1]. It stopped [1]."
    section = BriefSectionPrompt(
        outline=[BriefOutlineSection(title="Probe readings")], current=0
    )

    async def truncated(system, request, history, config, schema):
        if "Review the single sentence supplied" in system:
            assert json.dumps(draft) in request
            raise TruncatedAssistantResponse("Individual sentence could not be graded")
        raise TruncatedAssistantResponse("Batch exceeded its output limit")

    with pytest.raises(TruncatedAssistantResponse, match="Individual sentence"):
        await _review_finding_scope(
            draft,
            section,
            {1: {"title": "Probe log", "brief_subject_evidence": "Probe log"}},
            {},
            {},
            "Probes",
            {},
            truncated,
        )
