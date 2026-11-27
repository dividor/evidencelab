from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ui.backend.schemas.testing import TestResultRead as ResultRead
from ui.backend.services.brief_grading_errors import (
    brief_grading_error,
    grading_error_reason,
)
from ui.backend.services.test_evaluators import UnverifiedOverlapQuote

pytestmark = pytest.mark.unit


def test_row_explains_the_ungraded_check_separately_from_the_failed_claim():
    checks = [
        {
            "type": "brief_overlap",
            "error": True,
            "message": str(UnverifiedOverlapQuote()),
        },
        {
            "type": "brief_factual",
            "passed": False,
            "claim_grades": [
                {"claim": 8, "passed": True},
                {"claim": 9, "passed": False},
            ],
        },
    ]
    row = ResultRead(
        id=uuid4(),
        experiment_id=uuid4(),
        test_case_id=None,
        status="error",
        actual_output={"capability": "brief"},
        assertion_results=checks,
        error_message="An expectation could not be graded.",
        created_at=datetime.now(timezone.utc),
    )
    assert row.error_message == brief_grading_error(checks)
    assert (
        "Cross-section repetition: The repetition judge could not verify"
        in row.error_message
    )
    assert "Also failed: Factual support from citations (claim 9)." in row.error_message
    assert brief_grading_error(checks[1:]) is None


def test_custom_error_names_and_messages_are_safe():
    assert "timed out" in grading_error_reason(TimeoutError("private endpoint"))
    assert "private" not in grading_error_reason(
        ValueError("private model credentials")
    )
    assert (
        brief_grading_error(
            [
                {
                    "type": "llm_judge",
                    "label": "House style",
                    "error": True,
                    "message": "Timed out.",
                }
            ]
        )
        == "House style: Timed out."
    )
