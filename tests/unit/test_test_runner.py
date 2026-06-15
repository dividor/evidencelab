"""Unit tests for the evaluation-harness run engine (per-case evaluation).

Uses injected fake runners/judge-factories so the engine logic — error
isolation, pass/fail classification, latency capture, judge wiring — is tested
without touching the live search/LLM services.
"""

import pytest

from ui.backend.auth.testing_models import TestExperiment, TestRun
from ui.backend.services.test_runner import (
    _build_references,
    _combo_summary_model,
    _default_summary_model,
    _format_judge_context,
    _group_settings_to_config,
    _mirror_run_to_experiment,
    _parse_judgement,
    _references_text,
    _resolve_case_plan,
    _storable_output,
    effective_config,
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


async def test_effective_config_fills_models_from_combo(monkeypatch):
    import pipeline.db.config as cfg

    monkeypatch.setattr(
        cfg,
        "UI_MODEL_COMBOS",
        {
            "Combo X": {
                "embedding_model": "emb-1",
                "summarization_model": {"model": "sum-1"},
                "reranker_model": "rank-1",
            },
        },
    )
    out = effective_config({"model_combo": "Combo X"})
    assert out["embedding_model"] == "emb-1"
    assert out["summary_model"] == "sum-1"
    assert out["rerank_model"] == "rank-1"


async def test_effective_config_explicit_value_overrides_combo(monkeypatch):
    import pipeline.db.config as cfg

    monkeypatch.setattr(
        cfg,
        "UI_MODEL_COMBOS",
        {
            "Combo X": {
                "embedding_model": "emb-1",
                "summarization_model": {"model": "sum-1"},
            }
        },
    )
    out = effective_config({"model_combo": "Combo X", "summary_model": "override"})
    assert out["summary_model"] == "override"
    assert out["embedding_model"] == "emb-1"


async def test_group_settings_to_config_maps_keys_and_serializes():
    settings = {
        "rerank": True,
        "denseWeight": 0.7,
        "sectionTypes": ["findings", "recommendations"],
        "fieldBoostFields": {"country": 1, "organization": 0.5},
        "minChunkSize": 100,
    }
    out = _group_settings_to_config(settings)
    assert out["rerank"] is True
    assert out["dense_weight"] == 0.7
    assert out["min_chunk_size"] == 100
    assert out["section_types"] == "findings,recommendations"
    assert out["field_boost_fields"] == "country:1,organization:0.5"


async def test_group_settings_to_config_ignores_unset_and_bad_input():
    assert _group_settings_to_config(None) == {}
    assert _group_settings_to_config({"rerank": None}) == {}


async def test_build_references_maps_cited_markers_to_results():
    results = [
        {
            "title": "Kenya SMP",
            "organization": "WFP",
            "published_year": 2018,
            "doc_id": "d1",
            "country": "Kenya",
        },
        {"title": "Uganda CSP", "organization": "WFP", "doc_id": "d2"},
        {"title": "Kenya Education", "organization": "World Bank", "doc_id": "d3"},
    ]
    refs = _build_references("Enrolment rose [1] and gender parity [1, 3].", results)
    # Only cited results (1 and 3), de-duplicated and ordered.
    assert [r["number"] for r in refs] == [1, 3]
    assert refs[0]["title"] == "Kenya SMP"
    assert refs[1]["title"] == "Kenya Education"


async def test_build_references_ignores_out_of_range_citations():
    refs = _build_references("see [5]", [{"title": "only"}])
    assert refs == []


async def test_references_text_renders_appended_section():
    text = _references_text(
        [
            {
                "number": 1,
                "title": "Kenya SMP",
                "organization": "WFP",
                "year": 2018,
                "url": "http://x",
            }
        ]
    )
    assert "## References" in text
    assert "[1] Kenya SMP (WFP, 2018) — http://x" in text


async def test_storable_output_is_json_safe_and_trimmed():
    import json
    from datetime import datetime, timezone

    out = {
        "summary": "s",
        "search_results": [
            {
                "id": "1",
                "title": "T",
                "text": "x" * 5000,
                "published_date": datetime(2020, 1, 1, tzinfo=timezone.utc),
                "huge_field": "y" * 100000,
            }
        ],
    }
    safe = _storable_output(out)
    json.dumps(safe)  # must not raise (was failing on datetime)
    result = safe["search_results"][0]
    assert len(result["text"]) == 2000
    assert "huge_field" not in result  # bulky/unknown field dropped
    assert isinstance(result["published_date"], str)


async def test_mirror_run_to_experiment_copies_outcome_without_aliasing():
    stats = {"pass_rate": 0.5, "total": 4}
    run = TestRun(status="completed", summary_stats=stats)
    experiment = TestExperiment()
    _mirror_run_to_experiment(experiment, run)
    assert experiment.status == "completed"
    assert experiment.summary_stats == {"pass_rate": 0.5, "total": 4}
    # Must be a copy so mutating one does not corrupt the other.
    assert experiment.summary_stats is not run.summary_stats


async def test_resolve_case_plan_applies_llm_judge_override():
    matrix = {
        "columns": [{"type": "llm_judge", "rubric": "default", "threshold": 1}],
        "cases": {"c1": {"active": True, "cols": [True], "ovr": ["custom rubric"]}},
    }
    active, assertions = _resolve_case_plan(matrix, "c1")
    assert active is True
    assert assertions == [
        {"type": "llm_judge", "rubric": "custom rubric", "threshold": 1}
    ]


async def test_resolve_case_plan_blank_override_keeps_default_rubric():
    matrix = {
        "columns": [{"type": "llm_judge", "rubric": "default", "threshold": 1}],
        "cases": {"c1": {"active": True, "cols": [True], "ovr": ["   "]}},
    }
    _, assertions = _resolve_case_plan(matrix, "c1")
    assert assertions[0]["rubric"] == "default"


async def test_resolve_case_plan_override_only_affects_llm_judge():
    matrix = {
        "columns": [{"type": "min_results", "value": 1}],
        "cases": {"c1": {"active": True, "cols": [True], "ovr": ["ignored"]}},
    }
    _, assertions = _resolve_case_plan(matrix, "c1")
    assert assertions == [{"type": "min_results", "value": 1}]


async def test_format_judge_context_numbers_sources():
    out = {
        "search_results": [
            {"title": "Kenya SMP", "organization": "WFP", "text": "enrolment data"},
            {"title": "Uganda", "text": "x"},
        ]
    }
    ctx = _format_judge_context(out)
    assert "[1] Kenya SMP (WFP)" in ctx
    assert "enrolment data" in ctx
    assert "[2] Uganda" in ctx


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
