"""Regression cases for live Brief generation and its independent evaluation."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ui.backend.routes.testing import _case_input
from ui.backend.services import brief_experiment as brief
from ui.backend.services import test_runner as runner
from ui.backend.services.assistant_grounding import InvalidAssistantResponse
from ui.backend.services.brief_repetition import (
    BriefRepetitionCheck,
    _sibling_batches,
    remove_repeated_brief_findings,
)
from ui.backend.services.test_evaluators import evaluate_assertion

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


def draft(text="Processing time fell by half [7]."):
    return {
        "capability": "brief",
        "written": True,
        "summary": text,
        "words": 86,
        "assignment": {"heading": "Timeliness", "target_words": 100},
        "sources": [{"index": 7, "text": "Processing time fell by half."}],
        "siblings": [
            {"title": "Productivity", "content": "The team processed more requests."}
        ],
        "reference_standard": {"private_grading_example": "editor only"},
    }


@pytest.mark.parametrize(
    "text,passed",
    [
        ("Processing time fell by half [7].", True),
        ("", False),
        ("A claim [9].", False),
        ("A claim [?7].", False),
        ("## Another heading\nA finding [7].", False),
        ("**Another heading**\nA finding [7].", False),
    ],
)
def test_structure_checks_draft_and_returned_passages(text, passed):
    assert (
        evaluate_assertion({"type": "brief_structure"}, draft(text))["passed"] is passed
    )


@pytest.mark.parametrize(
    "count,passed", [(84, False), (85, True), (100, True), (115, True), (116, False)]
)
def test_word_count_uses_actual_section_target(count, passed):
    assert (
        evaluate_assertion({"type": "brief_length"}, {**draft(), "words": count})[
            "passed"
        ]
        is passed
    )


def test_invalid_case_rejected_during_edit():
    with pytest.raises(HTTPException, match="heading"):
        _case_input(
            SimpleNamespace(capability="brief"), {"query": "Topic", "target_words": 42}
        )


@pytest.mark.asyncio
async def test_generation_uses_real_request_contract_without_grading_material(
    monkeypatch,
):
    captured = {}

    async def stream(**options):
        captured.update(options)
        for event in [
            {"type": "search_status", "queries": [{"query": "timing records"}]},
            {"type": "token", "token": "Time fell [7]."},
            {"type": "sources", "sources": draft()["sources"]},
            {"type": "done", "section_written": True, "usage": {"prompt_tokens": 19}},
        ]:
            yield event

    monkeypatch.setattr(brief, "stream_research_response", stream)
    cfg = runner.run_config_snapshot({"rerank": False})
    brief.configure_brief(
        cfg, {"assistant_model": {"model": "writer", "temperature": 0.2}}
    )
    case = {
        "query": "Performance",
        "heading": "Timeliness",
        "guidance": "Use measurements",
        "voice": "Formal",
        "target_words": 100,
        "siblings": draft()["siblings"],
        "reference_standard": draft()["reference_standard"],
    }
    out = await brief.run_brief_case(case, cfg, "demo")
    assert "editor only" not in str(captured)
    assert (
        captured["brief_section"].outline[0].content == case["siblings"][0]["content"]
    )
    assert captured["brief_section"].current == 1 and captured["target_words"] == 100
    assert captured["model_key"] == "writer" and captured["reranker_model"] is None
    assert out["written"] and out["usage"]["prompt_tokens"] == 19 and out["words"] == 2
    assert out["searches"][0]["query"] == "timing records"


@pytest.mark.asyncio
async def test_overlap_judge_sees_both_sections_but_no_reference_answer(monkeypatch):
    call = AsyncMock(
        return_value=('{"reason":"Both sections report the same wait.","score":0}', {})
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    o = draft()
    assertion = {"type": "brief_overlap"}
    verdict = await runner.make_judge_factory({"judge_model": "grader"})(
        o, [assertion, assertion]
    )
    result = evaluate_assertion(assertion, o, verdict)
    assert not result["passed"] and "same wait" in result["message"]
    prompt, model, _system = call.await_args.args
    assert o["siblings"][0]["content"] in prompt and o["summary"] in prompt
    assert "editor only" not in prompt and model == "grader"
    call.assert_awaited_once()
    o["siblings"] = []
    cb = await brief.judge_brief(o, [assertion], "grader")
    assert "Provide another section" in evaluate_assertion(assertion, o, cb)["message"]


@pytest.mark.asyncio
async def test_invalid_judge_response_is_not_a_numeric_pass(monkeypatch):
    monkeypatch.setattr(runner, "_judge_call", AsyncMock(return_value=("1. Good", {})))
    with pytest.raises(ValidationError):
        await brief.judge_brief(
            draft(), [{"type": "llm_judge", "rubric": "Precision"}], "grader"
        )


@pytest.mark.asyncio
async def test_manual_sibling_can_duplicate_first_claim_and_distinct_finding_survives():
    async def check(system, prompt, *args):
        assert "It took two days." in prompt
        return BriefRepetitionCheck(duplicates=[1])

    result = await remove_repeated_brief_findings(
        "The work took 48 hours [7]. It cost five dollars [3].",
        {},
        check,
        [("Duration", "It took two days.")],
    )
    assert result == "It cost five dollars [3]."
    assert (
        list(_sibling_batches([("H", "abcdefghijk")], 6))[-1][0]["finding"] == "ghijk"
    )
    with pytest.raises(InvalidAssistantResponse):
        await remove_repeated_brief_findings(
            "First [7]. Second [8].",
            {},
            AsyncMock(return_value=BriefRepetitionCheck(duplicates=[1])),
        )


def test_default_cases_seed_editable_experiments_for_their_configured_libraries(
    monkeypatch,
):
    path = ROOT / "alembic/versions/0043_seed_brief_experiments.py"
    spec = importlib.util.spec_from_file_location("seed_brief_cases", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inserted = []
    monkeypatch.setattr(
        mod.op,
        "bulk_insert",
        lambda table, rows: inserted.extend((table.name, row) for row in rows),
    )
    monkeypatch.setattr(
        "pipeline.db.config.load_datasources_config",
        lambda: {
            "datasources": {"a": {"data_subdir": "uneg"}, "worldbank": {}, "other": {}}
        },
    )
    mod.upgrade()
    cases = [row for table, row in inserted if table == "test_cases"]
    experiments = [row for table, row in inserted if table == "test_experiments"]
    assert sorted(len(e["case_expectations"]["cases"]) for e in experiments) == [2, 6]
    assert len(cases) == 8 and len({c["id"] for c in cases}) == 8
    for c in cases:
        case = brief.BriefCase.model_validate(c["input"])
        assert case.siblings[0].content and case.reference_standard["source"]["text"]
        assert [x["supported"] for x in case.reference_standard["controls"]] == [
            True,
            False,
        ]
    for ex in experiments:
        matrix = ex["case_expectations"]
        assert {"brief_structure", "brief_length", "brief_overlap"} <= {
            a["type"] for a in matrix["columns"]
        }
        assert all(
            len(row["cols"]) == len(matrix["columns"])
            for row in matrix["cases"].values()
        )


@pytest.mark.asyncio
async def test_unwritten_section_fails_even_without_selected_expectations():
    output = {**draft(""), "written": False, "words": 0}
    outcome = await runner.evaluate_case({}, [], AsyncMock(return_value=output))
    assert (
        outcome["status"] == "fail"
        and outcome["assertion_results"][0]["type"] == "brief_structure"
    )


@pytest.mark.asyncio
async def test_run_as_group_uses_brief_prompt_checker_and_writer():
    import uuid

    group = SimpleNamespace(
        name="Reviewers",
        search_settings={
            "briefModel": "writer",
            "briefCitationCheck": False,
            "briefSectionPrompt": "Use technical prose.",
            "citationCheckModel": "checker",
        },
        summary_prompt=None,
    )
    config = await runner._apply_group(
        AsyncMock(get=AsyncMock(return_value=group)),
        {"capability": "brief", "group_id": str(uuid.uuid4())},
    )
    assert (
        config["brief_model"],
        config["brief_prompt"],
        config["brief_citation_check"],
        config["citation_model"],
    ) == ("writer", "Use technical prose.", False, "checker")
