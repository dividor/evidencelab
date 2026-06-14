"""Unit tests for the evaluation-harness run engine (per-case evaluation).

Uses injected fake runners/judge-factories so the engine logic — error
isolation, pass/fail classification, latency capture, judge wiring — is tested
without touching the live search/LLM services.
"""

import pytest

from ui.backend.services.test_runner import evaluate_case

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_evaluate_case_when_assertions_pass_then_status_pass():
    async def runner(_case_input):
        return {"results": [{"id": "A", "doc_id": "A", "score": 1.0}], "count": 1}

    outcome = await evaluate_case(
        {"query": "x"}, [{"type": "result_contains_id", "id": "A"}], runner
    )
    assert outcome["status"] == "pass"
    assert outcome["score"] == 1.0
    assert outcome["actual_output"]["count"] == 1
    assert outcome["error_message"] is None
    assert outcome["latency_ms"] is not None


async def test_evaluate_case_when_assertion_fails_then_status_fail():
    async def runner(_case_input):
        return {"results": [], "count": 0}

    outcome = await evaluate_case({}, [{"type": "min_results", "value": 1}], runner)
    assert outcome["status"] == "fail"
    assert outcome["score"] == 0.0
    assert outcome["actual_output"] == {"results": [], "count": 0}


async def test_evaluate_case_when_runner_raises_then_error_is_isolated():
    async def runner(_case_input):
        raise RuntimeError("boom in search")

    outcome = await evaluate_case({}, [{"type": "min_results", "value": 1}], runner)
    assert outcome["status"] == "error"
    assert "boom in search" in outcome["error_message"]
    assert outcome["actual_output"] is None
    assert outcome["assertion_results"] is None


async def test_evaluate_case_when_no_assertions_then_passes():
    async def runner(_case_input):
        return {"summary": "anything"}

    outcome = await evaluate_case({}, [], runner)
    assert outcome["status"] == "pass" and outcome["score"] == 1.0


async def test_evaluate_case_uses_injected_judge_factory():
    async def runner(_case_input):
        return {"summary": "a great, well-cited summary"}

    async def judge_factory(_output, _expectations):
        return lambda _text, _rubric: 0.9

    outcome = await evaluate_case(
        {},
        [{"type": "llm_judge", "rubric": "quality", "threshold": 0.7}],
        runner,
        judge_factory,
    )
    assert outcome["status"] == "pass"
    assert outcome["score"] == 0.9
