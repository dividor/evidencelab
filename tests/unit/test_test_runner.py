"""Unit tests for the evaluation-harness run engine (per-case evaluation).

Uses injected fake runners/judge-factories so the engine logic — error
isolation, pass/fail classification, latency capture, judge wiring — is tested
without touching the live search/LLM services.
"""

import uuid

import pytest

import ui.backend.services.test_runner as test_runner
from ui.backend.auth.testing_models import (
    TestCase,
    TestDataset,
    TestExperiment,
    TestRun,
)
from ui.backend.services.test_runner import (
    _active_case_plan,
    _build_references,
    _build_result_row,
    _combo_summary_model,
    _default_summary_model,
    _execute,
    _format_judge_context,
    _format_judge_references,
    _group_settings_to_config,
    _mirror_run_to_experiment,
    _parse_judgement,
    _progress_stats,
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
                "summarization_model": {
                    "model": "sum-1",
                    "max_tokens": 4000,
                    "temperature": 0.2,
                },
                "reranker_model": "rank-1",
            },
        },
    )
    out = effective_config({"model_combo": "Combo X"})
    assert out["embedding_model"] == "emb-1"
    assert out["summary_model"] == "sum-1"
    assert out["rerank_model"] == "rank-1"
    # The combo's summary token budget is applied so the summary isn't truncated.
    assert out["max_tokens"] == 4000
    # The UI never uses the combo's temperature (it always sends its own,
    # system default 0 or the group's), so the harness must not either.
    assert "temperature" not in out


async def test_effective_config_carries_combo_rerank_page_size(monkeypatch):
    import pipeline.db.config as cfg

    monkeypatch.setattr(
        cfg,
        "UI_MODEL_COMBOS",
        {"Combo X": {"reranker_model": "rank-1", "rerank_model_page_size": 10}},
    )
    out = effective_config({"model_combo": "Combo X"})
    assert out["max_rerank_candidates"] == 10
    explicit = effective_config({"model_combo": "Combo X", "max_rerank_candidates": 25})
    assert explicit["max_rerank_candidates"] == 25


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


async def test_build_references_carries_page_num():
    # The page of the cited chunk must be carried through so the rendered
    # References can show it, exactly as the search UI does.
    results = [{"title": "Kenya SMP", "page_num": 7}]
    refs = _build_references("finding [1]", results)
    assert refs[0]["page_num"] == 7


async def test_references_text_renders_appended_section():
    text = _references_text(
        [
            {
                "number": 1,
                "title": "Kenya SMP",
                "organization": "WFP",
                "year": 2018,
                "url": "http://x",
                "page_num": 12,
            }
        ]
    )
    assert "## References" in text
    # Grouped-by-document layout with the citation's page number, mirroring the
    # search UI's References list (no bare URL, unlike the old flat format).
    assert "Kenya SMP, WFP, 2018 | [1] p.12" in text


async def test_references_text_includes_page_ranges_per_document():
    # Two chunks of the same document cited on different pages group into one
    # References line, each citation keeping its own page number — the "page
    # ranges" the search UI shows and the eval harness previously dropped.
    references = [
        {"number": 1, "title": "Kenya SMP", "organization": "WFP", "page_num": 5},
        {"number": 3, "title": "Kenya SMP", "organization": "WFP", "page_num": 12},
    ]
    text = _references_text(references)
    assert "Kenya SMP, WFP | [1] p.5 [3] p.12" in text


async def test_references_text_omits_page_when_unknown():
    # A page of 0 (unknown) shows no page suffix, matching the frontend, which
    # only renders ``p.<page>`` for a truthy page number.
    text = _references_text([{"number": 1, "title": "No Page Doc", "page_num": 0}])
    assert "No Page Doc | [1]" in text
    assert "p.0" not in text


async def test_format_judge_references_grouped_with_pages():
    # The judge context uses the same grouped, page-numbered rendering (without
    # the markdown header) so what is judged matches what search shows.
    references = [
        {"number": 1, "title": "Kenya SMP", "organization": "WFP", "page_num": 5},
        {"number": 2, "title": "Kenya SMP", "organization": "WFP", "page_num": 9},
    ]
    text = _format_judge_references(references)
    assert text == "Kenya SMP, WFP | [1] p.5 [2] p.9"
    assert "## References" not in text


async def test_format_judge_references_empty_when_no_citations():
    assert _format_judge_references([]) == "(no citations resolved in the summary)"


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


async def test_progress_stats_reports_completed_and_total():
    assert _progress_stats(3, 10) == {"progress": {"completed": 3, "total": 10}}


async def test_active_case_plan_keeps_only_active_cases_with_assertions():
    cases = [
        TestCase(id=uuid.UUID("00000000-0000-0000-0000-000000000001"), input={}),
        TestCase(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), input={}),
        TestCase(id=uuid.UUID("00000000-0000-0000-0000-000000000003"), input={}),
    ]
    matrix = {
        "columns": [{"type": "min_results", "value": 1}],
        "cases": {
            "00000000-0000-0000-0000-000000000001": {"active": True, "cols": [True]},
            "00000000-0000-0000-0000-000000000002": {"active": False, "cols": [True]},
            # case 3 not in matrix -> inactive
        },
    }
    plan = _active_case_plan(matrix, cases)
    # Only the active case 1 is planned; total drives the progress denominator.
    assert len(plan) == 1
    planned_case, assertions = plan[0]
    assert planned_case is cases[0]
    assert assertions == [{"type": "min_results", "value": 1}]


async def test_active_case_plan_empty_when_no_cases_active():
    cases = [TestCase(id=uuid.uuid4(), input={})]
    assert _active_case_plan({}, cases) == []


async def test_build_result_row_compacts_output_and_sets_keys():
    experiment = TestExperiment(id=uuid.uuid4())
    run = TestRun(id=uuid.uuid4())
    case = TestCase(id=uuid.uuid4(), input={"query": "x"})
    outcome = {
        "status": "pass",
        "score": 1.0,
        "latency_ms": 12,
        "error_message": None,
        "actual_output": {"results": [{"id": "1", "text": "y" * 5000}]},
        "assertion_results": [{"type": "min_results", "passed": True}],
    }
    row = _build_result_row(experiment, run, case, outcome)
    assert row.experiment_id == experiment.id
    assert row.run_id == run.id
    assert row.test_case_id == case.id
    assert row.status == "pass"
    # Output is compacted: per-result text is trimmed to the storage limit.
    assert len(row.actual_output["results"][0]["text"]) == 2000


class _FakeResult:
    def scalar(self):
        return 0


class _FakeSession:
    """Minimal async-session stand-in that records summary_stats at each commit,
    so a test can assert progress is published incrementally."""

    def __init__(self, dataset):
        self._dataset = dataset
        self._run = None
        self.commits = []  # snapshot of run.summary_stats per commit
        self.added = []

    async def get(self, _model, _ident):
        return self._dataset

    async def execute(self, _stmt):
        return _FakeResult()

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, TestRun):
            self._run = obj

    async def commit(self):
        self.commits.append(self._run.summary_stats if self._run else None)

    async def refresh(self, _obj):
        return None

    async def rollback(self):
        return None


async def test_execute_publishes_incremental_progress(monkeypatch):
    async def fake_runner(_case_input):
        return {"results": [{"id": "A", "doc_id": "A"}], "count": 1}

    async def fake_factory(_output, _expectations):
        return lambda _text, _rubric: 0.0

    c1, c2 = uuid.uuid4(), uuid.uuid4()
    cases = [
        TestCase(id=c1, input={"query": "a"}),
        TestCase(id=c2, input={"query": "b"}),
    ]

    monkeypatch.setattr(test_runner, "build_case_runner", lambda *a, **k: fake_runner)
    monkeypatch.setattr(test_runner, "make_judge_factory", lambda _cfg: fake_factory)

    async def fake_load_cases(_session, _dataset_id):
        return cases

    monkeypatch.setattr(test_runner, "_load_cases", fake_load_cases)

    dataset_id = uuid.uuid4()
    dataset = TestDataset(id=dataset_id, capability="search", data_source="uneg")
    experiment = TestExperiment(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        status="pending",
        config=None,
        case_expectations={
            "columns": [{"type": "min_results", "value": 1}],
            "cases": {
                str(c1): {"active": True, "cols": [True]},
                str(c2): {"active": True, "cols": [True]},
            },
        },
    )
    session = _FakeSession(dataset)

    await _execute(session, experiment)

    progress = [c["progress"] for c in session.commits if c and "progress" in c]
    # 0/2 at start, then 1/2 and 2/2 as each case finishes.
    assert {"completed": 0, "total": 2} in progress
    assert {"completed": 1, "total": 2} in progress
    assert {"completed": 2, "total": 2} in progress
    # Final commit carries the real aggregate stats, not a progress marker.
    final = session.commits[-1]
    assert "progress" not in final
    assert final["pass_rate"] == 1.0 and final["total"] == 2
    assert experiment.status == "completed"
    # One persisted result row per active case.
    result_rows = [o for o in session.added if o.__class__.__name__ == "TestResult"]
    assert len(result_rows) == 2


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


# ---------------------------------------------------------------------------
# Token usage tracking (summary + judge calls → case totals → run rollup)
# ---------------------------------------------------------------------------


async def test_case_usage_totals_sums_summary_and_judge_per_model():
    output = {
        "usage": {
            "llm_model": "gpt-4.1-mini",
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        },
        "judge_usage": [
            {
                "llm_model": "gemini-2.0-flash",
                "prompt_tokens": 200,
                "completion_tokens": 100,
            },
        ],
    }
    totals = test_runner._case_usage_totals(output)
    assert totals["prompt_tokens"] == 1200
    assert totals["completion_tokens"] == 600
    # Cost is per-call from each call's own model rate:
    # gpt-4.1-mini: 1000*0.0004/1k + 500*0.0016/1k = 0.0012
    # gemini-2.0-flash: 200*0.0001/1k + 100*0.0004/1k = 0.00006
    assert float(totals["cost_usd"]) == pytest.approx(0.00126)


async def test_case_usage_totals_when_no_llm_calls_then_all_none():
    totals = test_runner._case_usage_totals({"results": [], "count": 0})
    assert totals == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
    }


async def test_evaluate_case_carries_usage_totals_into_outcome():
    async def runner(_case_input):
        return {
            "summary": "s",
            "usage": {
                "llm_model": "gpt-4.1-mini",
                "prompt_tokens": 10,
                "completion_tokens": 5,
            },
        }

    outcome = await evaluate_case({}, [], runner)
    assert outcome["prompt_tokens"] == 10
    assert outcome["completion_tokens"] == 5
    assert outcome["cost_usd"] is not None


async def test_evaluate_case_error_outcome_has_null_usage():
    async def runner(_case_input):
        raise RuntimeError("boom")

    outcome = await evaluate_case({}, [], runner)
    assert outcome["status"] == "error"
    assert outcome["prompt_tokens"] is None
    assert outcome["cost_usd"] is None


async def test_judge_factory_stashes_judge_usage_on_output(monkeypatch):
    async def fake_judge_call(_prompt, _model_key):
        return (
            '{"score": 1.0, "reason": "ok"}',
            {"llm_model": "gpt-4.1-mini", "prompt_tokens": 40, "completion_tokens": 8},
        )

    monkeypatch.setattr(test_runner, "_judge_call", fake_judge_call)
    factory = test_runner.make_judge_factory({"judge_model": "gpt-4.1-mini"})
    output = {"raw_summary": "text", "references": [], "search_results": []}
    judge_fn = await factory(
        output,
        [
            {"type": "llm_judge", "rubric": "r1"},
            {"type": "llm_judge", "rubric": "r1"},  # deduped — judged once
            {"type": "llm_judge", "rubric": "r2"},
        ],
    )
    # One usage entry per distinct rubric.
    assert len(output["judge_usage"]) == 2
    assert output["judge_usage"][0]["prompt_tokens"] == 40
    score, reason, _prompt = judge_fn("text", "r1")
    assert score == 1.0 and reason == "ok"


async def test_record_run_usage_writes_evaluation_activity_row(monkeypatch):
    from unittest.mock import AsyncMock

    recorded = AsyncMock(return_value=True)
    monkeypatch.setattr("ui.backend.services.usage_recorder.record_llm_usage", recorded)

    user_id = uuid.uuid4()
    dataset = TestDataset(id=uuid.uuid4(), capability="ai_summary", data_source="uneg")
    experiment = TestExperiment(
        id=uuid.uuid4(), dataset_id=dataset.id, name="My experiment"
    )
    run = TestRun(
        id=uuid.uuid4(),
        experiment_id=experiment.id,
        run_number=3,
        status="completed",
        created_by_user_id=user_id,
        summary_stats={
            "total": 4,
            "prompt_tokens": 4000,
            "completion_tokens": 900,
            "total_tokens": 4900,
            "cost_usd": 0.00304,
        },
    )
    await test_runner._record_run_usage(
        experiment, run, dataset, {"summary_model": "gpt-4.1-mini"}
    )

    recorded.assert_awaited_once()
    kwargs = recorded.await_args.kwargs
    assert kwargs["activity_type"] == "evaluation"
    assert kwargs["user_id"] == user_id
    assert kwargs["search_id"] == run.id
    assert kwargs["query"] == "Evaluation: My experiment (run 3)"
    assert kwargs["usage"] == {
        "llm_model": "gpt-4.1-mini",
        "prompt_tokens": 4000,
        "completion_tokens": 900,
    }
    assert float(kwargs["cost_usd"]) == pytest.approx(0.00304)
    assert kwargs["filters_extra"]["experiment_name"] == "My experiment"
    assert kwargs["filters_extra"]["data_source"] == "uneg"
    assert kwargs["filters_extra"]["cases"] == 4


async def test_execute_attributes_run_to_triggering_user(monkeypatch):
    async def fake_runner(_case_input):
        return {"results": [{"id": "A", "doc_id": "A"}], "count": 1}

    async def fake_factory(_output, _expectations):
        return lambda _text, _rubric: 0.0

    record_calls = []

    async def fake_record(experiment, run, dataset, cfg):
        record_calls.append(run)

    c1 = uuid.uuid4()
    cases = [TestCase(id=c1, input={"query": "a"})]
    monkeypatch.setattr(test_runner, "build_case_runner", lambda *a, **k: fake_runner)
    monkeypatch.setattr(test_runner, "make_judge_factory", lambda _cfg: fake_factory)
    monkeypatch.setattr(test_runner, "_record_run_usage", fake_record)

    async def fake_load_cases(_session, _dataset_id):
        return cases

    monkeypatch.setattr(test_runner, "_load_cases", fake_load_cases)

    dataset = TestDataset(id=uuid.uuid4(), capability="search", data_source="uneg")
    creator, clicker = uuid.uuid4(), uuid.uuid4()
    experiment = TestExperiment(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        status="pending",
        created_by_user_id=creator,
        config=None,
        case_expectations={
            "columns": [{"type": "min_results", "value": 1}],
            "cases": {str(c1): {"active": True, "cols": [True]}},
        },
    )
    session = _FakeSession(dataset)

    await _execute(session, experiment, triggered_by_user_id=clicker)

    # The run — and therefore its token usage — is attributed to whoever
    # clicked Run, not the experiment's creator.
    (run,) = [o for o in session.added if isinstance(o, TestRun)]
    assert run.created_by_user_id == clicker
    assert record_calls == [run]


# ---------------------------------------------------------------------------
# Run settings mirror the search UI: system defaults < run config < case params
# ---------------------------------------------------------------------------


async def test_effective_params_layers_ui_defaults_under_config_and_case(monkeypatch):
    monkeypatch.setattr(
        test_runner, "default_section_types", lambda: "findings,recommendations"
    )
    params = test_runner._effective_params(
        {"rerank": True, "dense_weight": None, "embedding_model": "emb"},
        {"query": "q", "params": {"min_chunk_size": 0}},
    )
    # UI system defaults, not the raw /search route defaults.
    assert params["dense_weight"] == 0.8  # None in config never overrides
    assert params["field_boost_fields"] == "country:1,organization:0.5"
    assert params["temperature"] == 0
    assert params["section_types"] == "findings,recommendations"
    # Run config and per-case params override in that order.
    assert params["rerank"] is True
    assert params["embedding_model"] == "emb"
    assert params["min_chunk_size"] == 0


async def test_effective_params_defaults_match_ui_when_nothing_is_set(monkeypatch):
    monkeypatch.setattr(test_runner, "default_section_types", lambda: "findings")
    params = test_runner._effective_params(None, {"query": "q"})
    assert params["rerank"] is True
    assert params["min_chunk_size"] == 100
    assert params["max_results"] == 20


def _fake_search_route(monkeypatch, captured, warning=None):
    """Stand in for ui.backend.routes.search so _run_search can run without the
    live retrieval stack. Records the kwargs it was called with."""
    import sys
    import types

    from ui.backend.services.search_models import note_search_warning

    async def _run_search_chunks(query, **kwargs):
        captured.update(kwargs)
        if warning:
            note_search_warning(warning)
        return ["raw"]

    def _fetch_and_build_results(pg, raw, source, limit, min_chunk_size):
        return [{"chunk_id": "c1", "text": "hello"}]

    def _apply_post_retrieval_boosts(built, *args):
        return built

    def _parse_section_types(raw):
        return raw.split(",") if raw else None

    fake = types.ModuleType("ui.backend.routes.search")
    fake._run_search_chunks = _run_search_chunks
    fake._fetch_and_build_results = _fetch_and_build_results
    fake._apply_post_retrieval_boosts = _apply_post_retrieval_boosts
    fake._parse_section_types = _parse_section_types
    monkeypatch.setitem(sys.modules, "ui.backend.routes.search", fake)
    monkeypatch.setattr(test_runner, "default_section_types", lambda: "findings")


async def test_run_search_uses_ui_defaults_and_group_overlay(monkeypatch):
    captured = {}
    _fake_search_route(monkeypatch, captured)
    out = await test_runner._run_search(
        {"query": "q"}, {"rerank": True, "section_types": "context"}, None, None, "src"
    )
    assert captured["dense_weight"] == 0.8
    assert captured["min_chunk_size"] == 100
    assert captured["rerank"] is True
    assert captured["section_types"] == ["context"]
    assert out["count"] == 1
    assert "warnings" not in out


async def test_run_search_reports_reranker_fallback_as_warning(monkeypatch):
    captured = {}
    _fake_search_route(monkeypatch, captured, warning="Reranker x unavailable")
    out = await test_runner._run_search({"query": "q"}, {}, None, None, "src")
    assert out["warnings"] == ["Reranker x unavailable"]
    assert out["count"] == 1  # still judged, not errored


async def test_run_summary_passes_search_warnings_through(monkeypatch):
    captured = {}
    _fake_search_route(monkeypatch, captured, warning="Reranker x unavailable")
    import ui.backend.services.llm_service as llm_service

    async def fake_summary(**kwargs):
        captured["summary_kwargs"] = kwargs
        return "Answer [1]", {"llm_model": "m"}

    monkeypatch.setattr(llm_service, "generate_ai_summary_with_usage", fake_summary)
    out = await test_runner._run_summary(
        {"query": "q"}, {"summary_model": "m"}, None, None, "src"
    )
    assert out["warnings"] == ["Reranker x unavailable"]
    # Summary settings follow the UI defaults too (temperature 0, cap 20).
    assert captured["summary_kwargs"]["temperature"] == 0
    assert captured["summary_kwargs"]["max_results"] == 20


# ---------------------------------------------------------------------------
# Per-run configuration snapshot (test_runs.config)
# ---------------------------------------------------------------------------


async def test_run_config_snapshot_records_resolved_models_and_settings(monkeypatch):
    monkeypatch.setattr(test_runner, "default_section_types", lambda: "findings")
    monkeypatch.setattr(test_runner, "_default_summary_model", lambda: "default-llm")
    snap = test_runner.run_config_snapshot(
        {
            "model_combo": "Combo X",
            "group_id": "g1",
            "group_name": "OEV",
            "rerank": True,
            "rerank_model": "rank-1",
            "max_rerank_candidates": 10,
        }
    )
    assert snap["model_combo"] == "Combo X"
    assert snap["group_name"] == "OEV"
    assert snap["rerank"] is True and snap["max_rerank_candidates"] == 10
    # UI system defaults are part of the snapshot, so a run is reproducible.
    assert snap["dense_weight"] == 0.8 and snap["min_chunk_size"] == 100
    assert snap["section_types"] == "findings"
    # Models fall back exactly as the run does; the judge defaults to the summary model.
    assert snap["summary_model"] == "default-llm"
    assert snap["judge_model"] == "default-llm"


async def test_run_config_snapshot_is_json_safe_and_keeps_explicit_judge(monkeypatch):
    import json

    monkeypatch.setattr(test_runner, "default_section_types", lambda: "")
    snap = test_runner.run_config_snapshot(
        {"summary_model": "sum", "judge_model": "judge", "max_tokens": 2000}
    )
    json.dumps(snap)
    assert snap["judge_model"] == "judge"
    assert snap["summary_model"] == "sum"


async def test_apply_group_records_group_name(monkeypatch):
    class FakeGroup:
        name = "OEV"
        search_settings = {"rerank": True}
        summary_prompt = "Be brief."

    class FakeSession:
        async def get(self, model, key):
            return FakeGroup()

    out = await test_runner._apply_group(FakeSession(), {"group_id": str(uuid.uuid4())})
    assert out["group_name"] == "OEV"
    assert out["rerank"] is True
    assert out["summary_prompt"] == "Be brief."
