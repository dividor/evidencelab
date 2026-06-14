"""Unit tests for the evaluation-harness run engine (per-case evaluation).

Uses injected fake runners/judge-factories so the engine logic — error
isolation, pass/fail classification, latency capture, judge wiring — is tested
without touching the live search/LLM services.
"""

import pytest

from ui.backend.auth.testing_models import TestExperiment, TestRun
from ui.backend.services.test_runner import (
    _combo_summary_model,
    _default_summary_model,
    _mirror_run_to_experiment,
    _parse_judgement,
    _resolve_case_plan,
    evaluate_case,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _matrix():
    return {
        "columns": [
            {"type": "min_results", "value": 1},
            {"type": "max_results", "value": 5},
        ],
        "cases": {
            "c1": {"active": True, "cols": [True, False]},
            "c2": {"active": True, "cols": [True, True]},
            "c3": {"active": False, "cols": [True, True]},
        },
    }


async def test_resolve_case_plan_returns_only_checked_columns():
    active, assertions = _resolve_case_plan(_matrix(), "c1")
    assert active is True
    assert assertions == [{"type": "min_results", "value": 1}]


async def test_resolve_case_plan_returns_all_checked_columns():
    active, assertions = _resolve_case_plan(_matrix(), "c2")
    assert active is True
    assert assertions == [
        {"type": "min_results", "value": 1},
        {"type": "max_results", "value": 5},
    ]


async def test_resolve_case_plan_inactive_case_is_skipped():
    assert _resolve_case_plan(_matrix(), "c3") == (False, [])


async def test_resolve_case_plan_unknown_case_is_skipped():
    assert _resolve_case_plan(_matrix(), "missing") == (False, [])


async def test_resolve_case_plan_empty_matrix_is_skipped():
    assert _resolve_case_plan({}, "c1") == (False, [])


async def test_parse_judgement_reads_json_score_and_reason():
    score, reason = _parse_judgement('{"score": 0.75, "reason": "good but terse"}')
    assert score == 0.75
    assert reason == "good but terse"


async def test_parse_judgement_falls_back_to_first_number():
    score, reason = _parse_judgement("I would rate this 0.4 overall")
    assert score == 0.4
    assert "0.4" in reason


async def test_mirror_run_to_experiment_copies_outcome_without_aliasing():
    stats = {"pass_rate": 0.5, "total": 4}
    run = TestRun(status="completed", summary_stats=stats)
    experiment = TestExperiment()
    _mirror_run_to_experiment(experiment, run)
    assert experiment.status == "completed"
    assert experiment.summary_stats == {"pass_rate": 0.5, "total": 4}
    # Must be a copy so mutating one does not corrupt the other.
    assert experiment.summary_stats is not run.summary_stats


async def test_resolve_case_plan_ignores_out_of_range_cols():
    matrix = {
        "columns": [{"type": "min_results", "value": 1}],
        "cases": {"c1": {"active": True, "cols": [True, True, True]}},
    }
    active, assertions = _resolve_case_plan(matrix, "c1")
    assert active is True
    assert assertions == [{"type": "min_results", "value": 1}]


async def test_combo_summary_model_extracts_nested_model():
    assert _combo_summary_model({"summarization_model": {"model": "m1"}}) == "m1"


async def test_combo_summary_model_when_absent_then_none():
    assert _combo_summary_model({}) is None
    assert _combo_summary_model(None) is None
    assert _combo_summary_model({"summarization_model": "not-a-dict"}) is None


async def test_default_summary_model_prefers_default_combo(monkeypatch):
    import pipeline.db.config as cfg

    monkeypatch.setattr(
        cfg,
        "UI_MODEL_COMBOS",
        {
            "A": {"summarization_model": {"model": "default-model"}},
            "B": {"summarization_model": {"model": "other-model"}},
        },
    )
    monkeypatch.setattr(cfg, "SUPPORTED_LLMS", {"fallback": {}})
    monkeypatch.setattr(cfg, "get_default_model_combo", lambda: "A")
    assert _default_summary_model() == "default-model"


async def test_default_summary_model_falls_back_to_supported_llm(monkeypatch):
    import pipeline.db.config as cfg

    monkeypatch.setattr(cfg, "UI_MODEL_COMBOS", {})
    monkeypatch.setattr(cfg, "SUPPORTED_LLMS", {"only-llm": {}})
    monkeypatch.setattr(cfg, "get_default_model_combo", lambda: "")
    assert _default_summary_model() == "only-llm"


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
