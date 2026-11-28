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
        ("An unsupported opening.\n\nA finding [7].", False),
        ("- A finding [7].", False),
        ("1. A finding [7].", False),
        ("A finding [7].\n\nThe review did not measure duration.", True),
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


@pytest.mark.parametrize(
    "text, limit, expected",
    [
        ("", 50, False),
        ("One point [7].", 0, True),
        ("An opening [7].\n\nA conclusion [7].", 0, True),
        ("A [7]. Another [7].\n\nB [7].\n\nC [7].", 50, False),
        ("A [7]. Another [7].\n\nB [7].\n\nC [7].", 67, True),
        ("A [7]. Another [7].\n\nB [7]. Related [7].\n\nC [7].", 50, True),
        ("Enough [7].", 101, False),
    ],
)
def test_paragraph_limit_is_configurable_and_allows_concise_sections(
    text, limit, expected
):
    result = evaluate_assertion(
        {"type": "brief_paragraphs", "max_percent": limit}, draft(text)
    )
    assert result["passed"] is expected


def test_invalid_case_rejected_during_edit():
    with pytest.raises(HTTPException, match="heading"):
        _case_input(
            SimpleNamespace(capability="brief"), {"query": "Topic", "target_words": 42}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_profile", [False, True])
async def test_generation_uses_real_request_contract_without_grading_material(
    monkeypatch,
    use_profile,
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
    cfg = runner.run_config_snapshot({"capability": "brief", "rerank": False})
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
    if use_profile:
        case["voice_profile"] = {
            "id": "4e0c70fc-978e-4332-90af-79e4007ffb4a",
            "name": "Operator bulletin",
            "instructions": "Address the operator in the second person.",
        }
        assert (
            _case_input(SimpleNamespace(capability="brief"), case)["voice_profile"]
            == case["voice_profile"]
        )
    out = await brief.run_brief_case(case, cfg, "demo")
    expected_voice = (
        case["voice_profile"]["instructions"] if use_profile else case["voice"]
    )
    assert (
        captured["brief_section"].voice_instructions
        == out["assignment"]["voice"]
        == expected_voice
    )
    assert out["assignment"]["voice_profile"] == case.get("voice_profile")
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
        return_value=(
            '{"reason":"Both sections report the same wait.",'
            '"repeats":[{"new_clause":"Processing time fell by half",'
            '"other_heading":"Earlier findings",'
            '"assessment":"Both report a 50% cut in processing time.",'
            '"existing_clause":"halved processing time"}]}',
            {},
        )
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    o = draft()
    o["siblings"] = [
        {"title": "Earlier findings", "content": "The team halved processing time."}
    ]
    assertion = {"type": "brief_overlap"}
    verdict = await runner.make_judge_factory({"judge_model": "grader"})(
        o, [assertion, assertion]
    )
    result = evaluate_assertion(assertion, o, verdict)
    assert not result["passed"] and "same wait" in result["message"]
    assert result["repetitions"] == [
        {
            "source_index": 0,
            "target_quote": "Processing time fell by half",
            "source_quote": "halved processing time",
            "assessment": "Both report a 50% cut in processing time.",
        }
    ]
    prompt, model, _system = call.await_args.args
    assert o["siblings"][0]["content"] in prompt and o["summary"] in prompt
    assert "editor only" not in prompt and model == "grader"
    call.assert_awaited_once()
    o["siblings"] = []
    cb = await brief.judge_brief(o, [assertion], "grader")
    assert "Provide another section" in evaluate_assertion(assertion, o, cb)["message"]


def test_editorial_judge_preserves_paragraphs_and_ends_with_requested_criterion():
    output = draft()
    output["summary"] = "Shifts changed [7].\n \nQueues cleared [7]."
    template = brief.assistant_prompt_templates.get_template(
        "brief_experiment_judge.j2"
    )
    rubric = "Check the voice for a general reader."
    issue, _, prompt = brief._brief_grade_request(template, output, "llm_judge", rubric)
    assert not issue
    assert 'Paragraph 1: "Shifts changed [7]."' in prompt
    assert 'Paragraph 2: "Queues cleared [7]."' in prompt
    assert "section contains 4 words" in prompt
    assert prompt.count("Queues cleared [7].") == 1
    assert prompt.strip().endswith(rubric)


def test_each_case_can_override_the_writing_rubric():
    column = {"type": "brief_writing", "rubric": "Check flow.", "threshold": 0.9}
    matrix = {
        "columns": [column],
        "cases": {
            "case": {"active": True, "cols": [True], "ovr": ["Check the opening."]}
        },
    }
    active, assertions = runner._resolve_case_plan(matrix, "case")
    assert active and assertions == [{**column, "rubric": "Check the opening."}]
    assert column["rubric"] == "Check flow."


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_voice_check_passes_without_an_applied_profile_and_never_calls_judge(
    monkeypatch, legacy
):
    from ui.backend.services.test_evaluators import _STARTER_VOICE_RUBRIC

    assertion = (
        {"type": "brief_writing", "rubric": _STARTER_VOICE_RUBRIC}
        if legacy
        else {"type": "brief_voice"}
    )
    output = draft()
    output["assignment"]["voice"] = "An audience note alone."
    call = AsyncMock()
    monkeypatch.setattr(runner, "_judge_call", call)
    grade = await brief.judge_brief(output, [assertion], "grader")
    result = evaluate_assertion(assertion, output, grade)
    assert result["passed"] and result["score"] == 1 and result["type"] == "brief_voice"
    assert "No voice and tone profile" in result["message"]
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_check_grades_against_the_exact_selected_instructions(monkeypatch):
    output = draft()
    output["assignment"]["voice_profile"] = {
        "name": "Service bulletin",
        "instructions": "Address the operator directly.",
    }
    call = AsyncMock(
        return_value=(
            '{"reason":"The draft never addresses the operator.",'
            '"unmet":["direct address"],"score":0.3}',
            {},
        )
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    assertion = {"type": "brief_voice"}
    selected = await brief.judge_brief(output, [assertion], "grader")
    result = evaluate_assertion(assertion, output, selected)
    assert not result["passed"] and result["score"] == 0.3
    assert "Address the operator directly." in result["judge_prompt"]
    assert (
        "Service bulletin" in result["judge_prompt"]
        and output["summary"] in result["judge_prompt"]
    )
    assert "editor only" not in result["judge_prompt"]


@pytest.mark.asyncio
async def test_writing_and_grounding_with_same_rubric_get_independent_inputs(
    monkeypatch,
):
    output = draft()
    output["sources"][0].update(
        title="Operations review",
        page=12,
        headings=["Timeliness"],
        bbox={"coordinates": [101, 202, 303, 404]},
    )
    rubric = "Is the text suitable?"
    criteria = [
        {"type": kind, "rubric": rubric, "label": label}
        for kind, label in (("llm_judge", "Evidence"), ("brief_writing", "Audience"))
    ]
    replies = AsyncMock(
        side_effect=[
            ('{"reason":"Missing context.","unmet":["scope"],"score":0.4}', {}),
            ('{"reason":"Suitable for the reader.","unmet":[],"score":1}', {}),
        ]
    )
    monkeypatch.setattr(runner, "_judge_call", replies)
    cb = await brief.judge_brief(output, criteria, "grader")
    results = [evaluate_assertion(a, output, cb) for a in criteria]
    assert [r["score"] for r in results] == [0.4, 1]
    assert [r["label"] for r in results] == ["Evidence", "Audience"]
    prompt = results[0]["judge_prompt"]
    assert all(
        text in prompt
        for text in (
            "Operations review",
            '"page": 12',
            '"index": 7',
            "Processing time fell by half.",
            "Timeliness",
        )
    )
    assert "bbox" not in prompt and "coordinates" not in prompt
    assert output["sources"][0]["bbox"]["coordinates"] == [101, 202, 303, 404]
    assert "editor only" in results[0]["judge_prompt"]
    assert "editor only" not in results[1]["judge_prompt"]
    assert "Productivity" not in results[1]["judge_prompt"]
    assert all(r["rubric"] == rubric for r in results)


@pytest.mark.asyncio
async def test_overlap_judge_retries_a_comparison_with_an_invented_quote(monkeypatch):
    replies = AsyncMock(
        side_effect=[
            (
                '{"reason":"Shared result.","repeats":[{"new_clause":"invented result",'
                '"other_heading":"Productivity","assessment":"More requests.",'
                '"existing_clause":"more requests"}]}',
                {},
            ),
            ('{"reason":"Different findings.","repeats":[]}', {}),
        ]
    )
    monkeypatch.setattr(runner, "_judge_call", replies)
    out = draft()
    a = {"type": "brief_overlap"}
    cb = await brief.judge_brief(out, [a], "grader")
    assert evaluate_assertion(a, out, cb)["passed"]
    assert len(out["judge_usage"]) == 2
    correction = replies.await_args_list[1].args[0]
    assert (
        "invented result" in correction and out["siblings"][0]["content"] in correction
    )


@pytest.mark.asyncio
async def test_unverifiable_repetition_quotes_report_which_check_errored(monkeypatch):
    from ui.backend.services.test_evaluators import UnverifiedOverlapQuote

    invalid = (
        '{"reason":"Duplicate.","repeats":[{"new_clause":"unknown",'
        '"other_heading":"Other","assessment":"Duplicate.","existing_clause":"invented"}]}'
    )
    monkeypatch.setattr(runner, "_judge_call", AsyncMock(return_value=(invalid, {})))
    result = await runner.evaluate_case(
        {},
        [{"type": "brief_overlap"}],
        AsyncMock(return_value=draft()),
        runner.make_judge_factory({"judge_model": "grader"}),
    )
    assert result["status"] == "error"
    assert result["error_message"] == str(UnverifiedOverlapQuote())
    assert result["actual_output"]["summary"] == draft()["summary"]


@pytest.mark.asyncio
async def test_invalid_judge_response_is_not_a_numeric_pass(monkeypatch):
    monkeypatch.setattr(runner, "_judge_call", AsyncMock(return_value=("1. Good", {})))
    with pytest.raises(ValidationError):
        await brief.judge_brief(
            draft(), [{"type": "llm_judge", "rubric": "Precision"}], "grader"
        )


def _repeat(label, *pairs):
    return BriefRepetitionCheck.model_validate(
        {
            "duplicates": [
                {
                    "id": label,
                    "pairs": [
                        {"new_clause": new, "existing_clause": earlier}
                        for new, earlier in pairs
                    ],
                }
            ]
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pairs",
    [
        [("Four units participated", "Four units took part")],
        [("Four units participated and eight later joined", "eight additional units")],
        [("Four units participated and eight later joined", "eight later joined")],
    ],
)
async def test_unproven_repeat_keeps_the_entire_paragraph(pairs):
    paragraph = (
        "Four units took part [1]. Four units participated and eight later joined [2]."
    )
    text = paragraph + "\n\nThe final count included the eight later joined units [3]."
    result = await remove_repeated_brief_findings(
        text, {}, AsyncMock(return_value=_repeat(2, *pairs))
    )
    assert result == text


@pytest.mark.asyncio
async def test_each_part_of_a_repeated_sentence_can_match_a_different_earlier_finding():
    text = (
        "One unit failed [1]. Two units recovered [2]. "
        "A single unit failed and two recovered [3]."
    )
    result = await remove_repeated_brief_findings(
        text,
        {},
        AsyncMock(
            return_value=_repeat(
                3,
                ("A single unit failed", "One unit failed"),
                ("and two recovered", "Two units recovered"),
            )
        ),
    )
    assert result == "One unit failed [1]. Two units recovered [2]."


@pytest.mark.asyncio
async def test_manual_sibling_can_duplicate_first_claim_and_distinct_finding_survives():
    async def check(system, prompt, *args):
        assert "It took two days." in prompt
        return _repeat(1, ("The work took 48 hours", "It took two days"))

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
            AsyncMock(
                return_value=_repeat(1, ("The work took 48 hours", "It took two days"))
            ),
        )


def test_installing_brief_evaluations_does_not_insert_examples():
    path = ROOT / "alembic/versions/0044_install_brief_starters.py"
    spec = importlib.util.spec_from_file_location("brief_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # A fresh install performs no database work in this revision.
    mod.upgrade()


@pytest.mark.asyncio
@pytest.mark.parametrize("infrastructure_error", [True, False])
async def test_case_distinguishes_an_editorial_rejection_from_a_service_error(
    infrastructure_error, monkeypatch
):
    reason = "The first sentence refers to a procedure the section never identifies."

    async def stream(**kwargs):
        if infrastructure_error:
            yield {"type": "error", "error": "Service unavailable"}
            return
        yield {"type": "brief_editorial_review", "issues": [reason]}
        yield {"type": "done", "section_written": False, "usage": {"prompt_tokens": 19}}

    monkeypatch.setattr(brief, "stream_research_response", stream)
    cfg = runner.run_config_snapshot({"capability": "brief", "rerank": False})
    brief.configure_brief(cfg, {"assistant_model": {"model": "writer"}})

    async def generate(case):
        return await brief.run_brief_case(case, cfg, "demo")

    result = await runner.evaluate_case(
        {"query": "Timing", "heading": "Methods", "target_words": 100}, [], generate
    )
    if infrastructure_error:
        assert result["status"] == "error"
        assert result["error_message"] == "Service unavailable"
        assert result["actual_output"] is None
    else:
        assert result["status"] == "error" and result["score"] is None
        assert not result["actual_output"]["written"]
        assert reason in result["actual_output"]["editorial_issues"]
        assert result["prompt_tokens"] == 19


@pytest.mark.asyncio
async def test_unwritten_section_is_an_error_even_without_selected_expectations():
    output = {**draft(""), "written": False, "words": 0}
    outcome = await runner.evaluate_case({}, [], AsyncMock(return_value=output))
    assert (
        outcome["status"] == "error"
        and outcome["score"] is None
        and outcome["error_message"] == "No Brief section was generated."
    )


@pytest.mark.asyncio
async def test_empty_draft_keeps_all_requested_checks_ungraded_and_never_calls_judge():
    output = {**draft("  "), "written": True, "words": 0}
    judge = AsyncMock()
    result = await runner.evaluate_case(
        {},
        [{"type": "brief_voice"}, {"type": "brief_length"}],
        AsyncMock(return_value=output),
        judge,
    )
    assert result["status"] == "error" and result["score"] is None
    assert [c["type"] for c in result["assertion_results"]] == [
        "brief_voice",
        "brief_length",
    ]
    assert all(c["not_run"] for c in result["assertion_results"])
    judge.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_inconsistent_perfect_grade_is_rechecked_and_both_calls_are_recorded(
    monkeypatch,
):
    replies = AsyncMock(
        side_effect=[
            (
                '{"reason":"The excerpt gives no frequency.",'
                '"unmet":["Frequency unsupported"],"score":1}',
                {},
            ),
            (
                '{"reason":"Occurrence only.","unmet":["Frequency unsupported"],"score":0.5}',
                {},
            ),
        ]
    )
    monkeypatch.setattr(runner, "_judge_call", replies)
    output = draft()
    a = {"type": "llm_judge", "rubric": "Check support."}
    cb = await brief.judge_brief(output, [a], "grader")
    result = evaluate_assertion(a, output, cb)
    assert result["score"] == 0.5 and not result["passed"]
    assert (
        len(output["judge_usage"]) == 2 and "must be below 1" in result["judge_prompt"]
    )


@pytest.mark.asyncio
async def test_paragraph_writer_preserves_prose_and_citations_after_repetition_review():
    from ui.backend.services.assistant_brief_writer import _brief_draft_text

    source = "The gate failed twice. Inspections found a loose contact. Cleaning restored service."
    prose = (
        "The gate failed twice [1]. "
        "Inspections found a loose contact [2].\n\n"
        "Cleaning restored service [3]."
    )
    quotes = {
        1: (4, "gate failed twice."),
        2: (9, "a loose contact"),
        3: (1, "Cleaning restored service"),
    }
    draft, issues, _ = _brief_draft_text(
        prose, {i: {"text": source} for i in [1, 4, 9]}, set(), quotes
    )
    assert not issues
    actual = await remove_repeated_brief_findings(
        draft, {}, AsyncMock(return_value=BriefRepetitionCheck(duplicates=[]))
    )
    assert actual == (
        "The gate failed twice [4]. Inspections found a loose contact [9].\n\n"
        "Cleaning restored service [1]."
    )
    invalid = "An unsubstantiated claim. A recorded failure [1]."
    retained, issues, _ = _brief_draft_text(
        invalid, {4: {"text": source}}, set(), quotes
    )
    assert retained == "A recorded failure [4]." and "numbered excerpt" in issues[0]


def test_comparison_keeps_all_supporting_passages_and_shared_passages_are_numbered_once():
    from ui.backend.services.assistant_brief_writer import _brief_draft_text

    sources = {
        8: {"text": "Time fell in the first group. The change lasted a year."},
        2: {"text": "Time rose in the other group."},
    }
    quotes = {
        1: (8, "Time fell in the first group."),
        2: (8, "The change lasted a year."),
        3: (2, "Time rose in the other group."),
    }
    prose, issues, support = _brief_draft_text(
        "The groups moved in opposite directions [1][2][3].", sources, set(), quotes
    )
    assert not issues and prose == "The groups moved in opposite directions [8, 2]."
    assert [q.citation for q in support[prose]] == [8, 8, 2]


@pytest.mark.asyncio
async def test_parent_case_passes_child_outline_to_writer_and_grader(monkeypatch):
    children = [
        {"title": "Duration"},
        {"title": "Cost", "content": "Each repair cost ten dollars."},
    ]

    async def stream(**args):
        section = args["brief_section"]
        assert section.current == 0 and [s.level for s in section.outline] == [1, 2, 2]
        assert section.outline[2].content == children[1]["content"]
        yield {"type": "token", "token": "Each repair cost ten dollars [1]."}
        yield {"type": "done", "section_written": True}

    monkeypatch.setattr(brief, "stream_research_response", stream)
    config = runner.run_config_snapshot({"capability": "brief"})
    brief.configure_brief(config, {})
    output = await brief.run_brief_case(
        {"query": "Repairs", "heading": "Overview", "children": children},
        config,
        "demo",
    )
    call = AsyncMock(
        return_value=(
            '{"reason":"The parent answers Cost.","unmet":["ten dollars"],"score":0}',
            {},
        )
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    assert output["assignment"]["outline_headings"] == ["Overview", "Duration", "Cost"]
    overlap = {"type": "brief_intro_scope"}
    callback = await brief.judge_brief(output, [overlap], "grader")
    assert not evaluate_assertion(overlap, output, callback)["passed"]
    prompt = call.await_args.args[0]
    assert 'Questions reserved for the children: ["Duration", "Cost"]' in prompt
    assert "introduction in place of reading" in prompt


@pytest.mark.parametrize("details,expected", [([], 1.0), (["five defects"], 0.0)])
def test_parent_scope_scores_only_the_specific_details_found(details, expected):
    assert (
        brief.IntroductionVerdict(
            reason="Compared with child assignments.", unmet=details
        ).score
        == expected
    )


def test_source_context_is_available_but_only_selected_findings_are_citable():
    from ui.backend.services.brief_evidence_selection import _draft_excerpts

    passages = {11: {"title": "Inspection record"}}
    text, quotes = _draft_excerpts(
        passages,
        {11: ["Applies to the north site.", "A seal failed.", "A seal failed."]},
    )
    assert "Subject: Applies to the north site." in text
    assert quotes == {1: (11, "A seal failed.")}


def test_overlapping_chunks_share_an_excerpt_only_within_the_same_source_and_subject():
    from ui.backend.services.brief_evidence_selection import _draft_excerpts

    passages = {
        i: {"doc_id": doc, "title": "Inspection record"}
        for i, doc in enumerate(["A", "A", "A", "B"], 1)
    }
    selected = {
        i: [subject, "A seal failed."]
        for i, subject in enumerate(["North", "North", "South", "North"], 1)
    }
    text, quotes = _draft_excerpts(passages, selected)
    assert "Source 2:" not in text
    assert list(quotes.values()) == [(i, "A seal failed.") for i in (1, 3, 4)]


def test_word_target_preserves_the_order_of_the_explanation():
    from ui.backend.services.assistant_brief_writer import _fit_section_to_target

    opening = "The team inspected every joint in the new system [1]."
    cause = (
        "They found that seals next to an exposed pipe cracked during the freeze [2]."
    )
    consequence = "This delayed repairs [3]."
    paragraph = f"{opening} {cause} {consequence}"
    assert _fit_section_to_target(paragraph, 13) == (opening, 9)
    assert _fit_section_to_target(paragraph, 20) == (f"{opening} {cause}", 22)


def test_revision_notes_require_every_cited_source_and_preserve_paragraphs():
    from ui.backend.services.assistant_brief_writer import _revision_notes

    draft = (
        "Both detectors recorded the change [2, 4]. The other sample broke [2, 8]."
        "\n\nThe later reading was stable [4]."
        "\n\nThe sources leave the cause open."
    )
    assert _revision_notes(draft, {2, 4}) == (
        "Both detectors recorded the change.\n\nThe later reading was stable."
    )


@pytest.mark.asyncio
async def test_relevance_requires_an_explained_deduction_and_keeps_positives(
    monkeypatch,
):
    output = draft()
    assertion = {
        "type": "llm_judge",
        "label": "Relevance to the template and section",
        "rubric": "Compare the two workshops.",
    }
    call = AsyncMock(
        side_effect=[
            ('{"negatives":[],"positives":["Addresses maintenance."],"score":0.9}', {}),
            (
                '{"negatives":["The second workshop is missing."],'
                '"positives":["Addresses maintenance."],"score":0.6}',
                {},
            ),
        ]
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    grade = await brief.judge_brief(output, [assertion], "grader")
    result = evaluate_assertion(assertion, output, grade)
    assert not result["passed"] and result["score"] == 0.6
    assert result["relevance"] == {
        "negatives": ["The second workshop is missing."],
        "positives": ["Addresses maintenance."],
    }
    assert call.await_count == 2
    assert "target_words" not in result["judge_prompt"]
    assert "words after excluding citation markers" not in result["judge_prompt"]
    assert "on-topic qualitative answer" in result["judge_prompt"]
    assert "Compare the two workshops." in result["judge_prompt"]


@pytest.mark.asyncio
async def test_relevance_can_give_full_credit_to_an_on_topic_qualitative_answer(
    monkeypatch,
):
    from ui.backend.services.brief_template_evaluation import DEFAULT_BRIEF_EXPECTATIONS

    assertion = next(
        a
        for a in DEFAULT_BRIEF_EXPECTATIONS
        if a.get("label") == "Relevance to the template and section"
    )
    output = draft("Technicians described faster repairs [7].")
    output["assignment"]["outline_headings"] = ["Repair time", "Operating costs"]
    call = AsyncMock(
        return_value=(
            '{"negatives":[],"positives":["Reports the requested experience."],"score":1}',
            {},
        )
    )
    monkeypatch.setattr(runner, "_judge_call", call)
    grade = await brief.judge_brief(output, [assertion], "grader")
    result = evaluate_assertion(assertion, output, grade)
    assert result["passed"] and result["relevance"]["negatives"] == []
    assert '"outline": ["Repair time", "Operating costs"]' in result["judge_prompt"]
    call.assert_awaited_once()
