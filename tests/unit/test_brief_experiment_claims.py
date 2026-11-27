from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ui.backend.schemas.testing import TestResultRead as ResultRead
from ui.backend.services.brief_experiment_claims import (
    brief_claim_evidence,
    link_assessment_claims,
)

pytestmark = pytest.mark.unit


def test_saved_result_maps_each_claim_to_its_own_numbered_sources():
    output = {
        "capability": "brief",
        "summary": (
            "Pressure held [7, 2][7]. Pressure later fell [2].\n\n"
            "No estimate was available. The pump stopped [9][?7]."
        ),
        "sources": [
            {"index": 2, "text": "Gauge B"},
            {"index": 10, "text": "Unused"},
            {"index": 7, "text": "Gauge A"},
        ],
    }
    result = ResultRead(
        id=uuid4(),
        experiment_id=uuid4(),
        test_case_id=uuid4(),
        status="fail",
        actual_output=output,
        created_at=datetime.now(timezone.utc),
    )
    view = result.model_dump()["brief_evidence"]
    first, second = view["paragraphs"]
    assert [c["references"] for c in first + second] == [[0, 1], [1], [], [2, 3]]
    assert [r["label"] for r in view["references"]] == ["7", "2", "9", "?7"]
    assert [r["source_position"] for r in view["references"]] == [2, 0, None, None]
    assert [p["text"] for p in first[0]["parts"] if p.get("marker")] == [
        "[7, 2]",
        "[7]",
    ]
    prose = "\n\n".join(
        " ".join("".join(p["text"] for p in c["parts"]) for c in para)
        for para in view["paragraphs"]
    )
    assert prose == output["summary"]
    assert result.actual_output == output


@pytest.mark.parametrize(
    "output",
    [
        None,
        {"capability": "ai_summary", "summary": "A [1]."},
        {"capability": "brief", "summary": ""},
        {"capability": "brief", "written": False, "summary": "A previous draft."},
    ],
)
def test_only_generated_brief_sections_have_claim_details(output):
    assert brief_claim_evidence(output) is None


def test_only_claims_quoted_in_this_assessment_are_linked():
    view = brief_claim_evidence(
        {
            "capability": "brief",
            "summary": "Pressure fell [4].\n\nThe new valve held steady [9].",
        }
    )
    assessments = [
        {
            "message": "The source supports ‘a different claim’. It documents “held steady”."
        },
        {"message": "The section discusses pressure."},
    ]
    results = link_assessment_claims(assessments, view)
    assert [r["quoted_claims"] for r in results] == [[1], []]
    assert all("quoted_claims" not in a for a in assessments)
