"""Exercise the factual support assertion through the experiment runner."""

import json
from unittest.mock import AsyncMock

import pytest

from ui.backend.services import test_runner
from ui.backend.services.brief_experiment import judge_brief
from ui.backend.services.test_evaluators import evaluate_assertion

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
RUBRIC = "Check factual grounding against the cited excerpts. Check all amounts."


def output():
    return {
        "capability": "brief",
        "written": True,
        "summary": "Costs fell [4].\n\nThe saving was ten percent [9].",
        "sources": [
            {"index": 4, "text": "Costs dropped.", "bbox": [1, 2, 3]},
            {"index": 9, "text": "Ten pounds were saved."},
            {"index": 8, "text": "Unused excerpt."},
        ],
    }


def reply(grades):
    return json.dumps(
        {
            "claims": [
                {
                    "claim": n,
                    "factual": True,
                    "score": score,
                    "reason": reason,
                    "supporting_quotes": (
                        [
                            (
                                {"citation": 9, "quote": "Ten pounds were saved."}
                                if n == 2 and score == 0.4
                                else {"citation": 4, "quote": "Costs dropped."}
                            )
                        ]
                        if score
                        else []
                    ),
                    "unmet": [] if score == 1 else ["Unsupported detail."],
                }
                for n, score, reason in grades
            ]
        }
    ), {"prompt_tokens": 10}


async def test_scores_match_each_claim_and_its_configured_threshold(monkeypatch):
    o = {
        **output(),
        "reference_standard": {
            "scope_notes": "Check units reported.",
            "source": {"bbox": [42]},
        },
    }
    check = {"type": "llm_judge", "rubric": RUBRIC}
    call = AsyncMock(
        return_value=reply(
            [(2, 0.4, "Different units."), (1, 1, "The log confirms the decrease.")]
        )
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    grade = await judge_brief(o, [check, {**check, "threshold": 0.4}], "model")
    result = evaluate_assertion(check, o, grade)
    assert result["type"] == "brief_factual"
    assert result["score"] == 0.4 and not result["passed"]
    assert [(g["claim"], g["score"], g["passed"]) for g in result["claim_grades"]] == [
        (1, 1, True),
        (2, 0.4, False),
    ]
    assert result["claim_grades"][1]["reason"] == "Different units."
    assert all(
        s in result["judge_prompt"]
        for s in ("Costs dropped.", "Ten pounds were saved.", RUBRIC)
    )
    assert (
        "Unused excerpt." not in result["judge_prompt"]
        and "bbox" not in result["judge_prompt"]
    )
    assert result["claim_grades"][1]["verdict"] == "partially_supported"
    relaxed = evaluate_assertion({**check, "threshold": 0.4}, o, grade)
    assert relaxed["passed"] and relaxed["threshold"] == 0.4
    assert relaxed["claim_grades"][1]["verdict"] == "partially_supported"
    call.assert_awaited_once()


@pytest.mark.parametrize(
    "bad",
    [
        [(2, 1, "Okay.")],
        [(1, 1, "Okay."), (1, 1, "Again.")],
        [(1, 1, "Yes."), (3, 1, "Yes.")],
        [(1, 2, "Yes.")],
    ],
)
async def test_requires_one_valid_grade_for_every_claim(monkeypatch, bad):
    call = AsyncMock(side_effect=[reply(bad), reply(bad)])
    monkeypatch.setattr(test_runner, "_judge_call", call)
    o = output()
    check = {"type": "brief_factual", "rubric": "Check the units."}
    result = evaluate_assertion(check, o, await judge_brief(o, [check], "model"))
    assert result["error"] and "score" not in result
    assert len(result["claim_grades"]) == 2
    assert any(g.get("error") for g in result["claim_grades"])
    assert len(o["judge_usage"]) == 2


async def test_long_section_groups_claims_and_can_correct_an_incomplete_verdict(
    monkeypatch,
):
    call = AsyncMock(
        side_effect=[
            reply([]),
            reply([(n, 1, "Supported.") for n in range(1, 9)]),
            reply([(9, 0, "No excerpt.")]),
        ]
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    o = {
        **output(),
        "summary": " ".join(f"Measurement {n} fell [4]." for n in range(1, 9))
        + " It fell again.",
    }
    check = {"type": "brief_factual", "rubric": "Check the quantities."}
    grade = await judge_brief(o, [check], "model")
    result = evaluate_assertion(check, o, grade)
    assert len(result["claim_grades"]) == 9 and result["score"] == 0
    assert "Costs dropped." not in call.await_args.args[0]
    assert len(o["judge_usage"]) == 3


async def test_unwritten_draft_and_case_override(monkeypatch):
    o = {**output(), "written": False, "summary": ""}
    col = {"type": "llm_judge", "rubric": RUBRIC}
    matrix = {
        "columns": [col],
        "cases": {"c": {"active": True, "cols": [True], "ovr": ["Check numbers."]}},
    }
    _, checks = test_runner._resolve_case_plan(matrix, "c", "brief")
    assert checks == [{"type": "brief_factual", "rubric": "Check numbers."}]
    assert (
        test_runner._resolve_case_plan(matrix, "c", "ai_summary")[1][0]["type"]
        == "llm_judge"
    )
    call = AsyncMock()
    monkeypatch.setattr(test_runner, "_judge_call", call)
    result = evaluate_assertion(checks[0], o, await judge_brief(o, checks, "model"))
    assert not result["passed"] and result["message"] == "No section was written."
    call.assert_not_awaited()


async def test_a_perfect_score_with_an_unmet_requirement_is_rechecked(monkeypatch):
    invalid = {
        "claims": [
            {
                "claim": 1,
                "reason": "Amount missing.",
                "factual": True,
                "unmet": ["amount"],
                "score": 1,
            }
        ]
    }
    call = AsyncMock(
        side_effect=[(json.dumps(invalid), {}), reply([(1, 0.5, "Amount missing.")])]
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    o = {**output(), "summary": "Costs fell by half [4]."}
    check = {"type": "brief_factual", "rubric": "Check the amount."}
    grade = await judge_brief(o, [check], "model")
    assert evaluate_assertion(check, o, grade)["claim_grades"][0]["score"] == 0.5
    assert len(o["judge_usage"]) == 2


async def test_cannot_award_credit_to_an_uncited_fact_but_accepts_a_transition(
    monkeypatch,
):
    passage = {
        "claim": 2,
        "factual": False,
        "unmet": [],
        "reason": "Introduces the next topic.",
        "score": 1,
    }
    grade = {
        "claim": 1,
        "factual": True,
        "unmet": [],
        "reason": "The draft says so.",
        "score": 1,
    }
    call = AsyncMock(
        side_effect=[
            (json.dumps({"claims": [grade, passage]}), {}),
            (
                json.dumps(
                    {
                        "claims": [
                            {
                                **grade,
                                "score": 0,
                                "reason": "There is no cited evidence.",
                            },
                            passage,
                        ]
                    }
                ),
                {},
            ),
        ]
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    o = {
        **output(),
        "summary": "The instrument failed. We now turn to the next question.",
    }
    check = {"type": "brief_factual", "rubric": "Check factual support."}
    verdict = await judge_brief(o, [check], "model")
    assert [
        g["score"] for g in evaluate_assertion(check, o, verdict)["claim_grades"]
    ] == [0, 1]
    assert "no cited excerpt: [1]" in call.await_args.args[0]


async def test_unverified_quotation_retries_only_that_claim_and_preserves_other_grades(
    monkeypatch,
):
    valid = {
        "claim": 1,
        "factual": True,
        "score": 1,
        "unmet": [],
        "reason": "Recorded in the log.",
        "supporting_quotes": [{"citation": 4, "quote": "Costs dropped."}],
    }
    wrong = {
        **valid,
        "claim": 2,
        "supporting_quotes": [{"citation": 9, "quote": "Profits rose sharply."}],
    }
    call = AsyncMock(
        side_effect=[
            (json.dumps({"claims": [valid, wrong]}), {}),
            (json.dumps({"claims": [wrong]}), {}),
        ]
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    o = output()
    check = {"type": "brief_factual", "rubric": RUBRIC}
    result = evaluate_assertion(check, o, await judge_brief(o, [check], "model"))
    assert result["passed"] is False and result["score"] == 0
    assert result["claim_grades"][0]["passed"]
    assert result["claim_grades"][1]["passed"] is False
    assert result["claim_grades"][1]["evidence_failed"]
    assert "could not be found in [9]" in result["claim_grades"][1]["reason"]
    assert "Costs dropped." not in call.await_args.args[0]


async def test_retry_can_substantiate_a_claim_using_only_the_relevant_excerpt(
    monkeypatch,
):
    o = {**output(), "summary": "Costs fell [4, 9]."}
    good, usage = reply([(1, 1, "The log confirms the decrease.")])
    wrong = json.loads(good)
    wrong["claims"][0]["supporting_quotes"].append(
        {"citation": 9, "quote": "The costs were lower."}
    )
    call = AsyncMock(side_effect=[(json.dumps(wrong), usage), (good, usage)])
    monkeypatch.setattr(test_runner, "_judge_call", call)
    check = {"type": "brief_factual", "rubric": RUBRIC}
    grade = await judge_brief(o, [check], "model")
    result = evaluate_assertion(check, o, grade)
    assert result["passed"] and result["score"] == 1
    assert call.await_count == 2


@pytest.mark.parametrize("sources", [[], [{"index": 4, "text": "Costs dropped."}]])
async def test_completed_grade_without_evidence_fails_even_at_zero_threshold(
    monkeypatch, sources
):
    o = {**output(), "summary": "Costs fell [4].", "sources": sources}
    raw, usage = reply([(1, 1, "Costs decreased.")])
    row = json.loads(raw)["claims"][0]
    row["supporting_quotes"] = []
    call = AsyncMock(return_value=(json.dumps({"claims": [row]}), usage))
    monkeypatch.setattr(test_runner, "_judge_call", call)
    check = {"type": "brief_factual", "rubric": RUBRIC, "threshold": 0}
    grade = await judge_brief(o, [check], "model")
    result = evaluate_assertion(check, o, grade)
    if not sources:
        assert (
            result["error"] and result["claim_grades"][0]["outcome"] == "missing_source"
        )
        assert call.await_count == 1
    else:
        assert result["passed"] is False and result["score"] == 0
        assert result["claim_grades"][0]["passed"] is False
        assert call.await_count == 2


async def test_partial_score_without_a_named_gap_retries_and_retains_the_corrected_grade(
    monkeypatch,
):
    raw, usage = reply(
        [(2, 0.4, "The source gives a currency amount, not a percentage.")]
    )
    records = json.loads(raw)
    records["claims"][0]["unmet"] = []
    first, _ = reply([(1, 1, "Costs fell.")])
    records["claims"].extend(json.loads(first)["claims"])
    call = AsyncMock(side_effect=[(json.dumps(records), usage), (raw, usage)])
    monkeypatch.setattr(test_runner, "_judge_call", call)
    draft = output()
    check = {"type": "brief_factual", "rubric": RUBRIC}
    result = evaluate_assertion(
        check, draft, await judge_brief(draft, [check], "model")
    )
    partial = result["claim_grades"][1]
    assert partial["verdict"] == "partially_supported"
    assert partial["unmet"] and partial["supporting_quotes"]
    assert call.await_count == 2


@pytest.mark.parametrize("failing", [True, False])
async def test_inconsistent_transition_is_retried_without_changing_the_score_silently(
    monkeypatch, failing
):
    draft = {**output(), "summary": "Evidence was unavailable."}
    grade = dict(claim=1, score=0, factual=False, reason="No evidence.", unmet=[])
    fixed = {**grade, "factual": True}
    call = AsyncMock(
        side_effect=[
            (json.dumps({"claims": [g]}), {})
            for g in (grade, grade if failing else fixed)
        ]
    )
    monkeypatch.setattr(test_runner, "_judge_call", call)
    check = dict(type="brief_factual", rubric=RUBRIC)
    result = evaluate_assertion(
        check, draft, await judge_brief(draft, [check], "model")
    )
    [claim] = result["claim_grades"]
    assert call.await_count == 2 and "nonfactual transition" in call.await_args.args[0]
    if failing:
        assert claim["error"] and claim["outcome"] == "grading_error"
        assert claim["verdict"] == "cannot_assess"
    else:
        assert claim["outcome"] == "uncited" and claim["score"] == 0


async def test_repair_prompt_shows_the_required_quote_fields_for_a_keyed_quote(
    monkeypatch,
):
    draft = {**output(), "summary": "Costs fell [4]."}
    correct, usage = reply([(1, 1, "Costs fell.")])
    invalid = json.loads(correct)
    quote = invalid["claims"][0]["supporting_quotes"][0]
    invalid["claims"][0]["supporting_quotes"] = [
        {str(quote["citation"]): quote["quote"]}
    ]
    judge = AsyncMock(side_effect=[(json.dumps(invalid), usage), (correct, usage)])
    monkeypatch.setattr(test_runner, "_judge_call", judge)
    check = dict(type="brief_factual", rubric=RUBRIC)
    result = evaluate_assertion(
        check, draft, await judge_brief(draft, [check], "model")
    )
    assert result["passed"]
    assert (
        "Each supporting quote must contain a citation number"
        in judge.await_args.args[0]
    )
    assert '{"citation":4,"quote":' in judge.await_args.args[0]


async def test_repair_locates_quotes_across_only_the_claims_own_references(monkeypatch):
    draft = {**output(), "summary": "Costs fell and demand rose [4, 9]."}
    good, usage = reply([(1, 1, "Both changes were recorded.")])
    correct = json.loads(good)
    draft["sources"][1]["text"] = "Demand rose."
    draft["sources"][2]["text"] = "Demand rose."
    correct["claims"][0]["supporting_quotes"].append(
        {"citation": 9, "quote": "Demand rose."}
    )
    wrong = json.loads(json.dumps(correct))
    wrong["claims"][0]["supporting_quotes"][1]["citation"] = 4
    judge = AsyncMock(
        side_effect=[(json.dumps(answer), usage) for answer in (wrong, correct)]
    )
    monkeypatch.setattr(test_runner, "_judge_call", judge)
    check = dict(type="brief_factual", rubric=RUBRIC)
    result = evaluate_assertion(
        check, draft, await judge_brief(draft, [check], "model")
    )
    prompt = judge.await_args.args[0]
    assert '"found_in": {"9": "verbatim"}' in prompt
    assert '"found_in": {"4": "verbatim"}' in prompt
    assert '"8":' not in prompt
    assert result["passed"] and result["score"] == 1


async def test_quote_found_in_another_reference_cannot_automatically_award_credit(
    monkeypatch,
):
    draft = {**output(), "summary": "The second report found costs fell [4, 9]."}
    bad, usage = reply([(1, 1, "Costs fell.")])
    response = json.loads(bad)
    response["claims"][0]["supporting_quotes"][0]["citation"] = 9
    grade = {
        **response["claims"][0],
        "supporting_quotes": [],
        "score": 0,
        "unmet": ["The second report did not report falling costs."],
        "reason": "Only the first report observed a drop.",
    }
    judge = AsyncMock(
        side_effect=[
            (json.dumps(response), usage),
            (json.dumps({"claims": [grade]}), usage),
        ]
    )
    monkeypatch.setattr(test_runner, "_judge_call", judge)
    check = dict(type="brief_factual", rubric=RUBRIC)
    result = evaluate_assertion(
        check, draft, await judge_brief(draft, [check], "model")
    )
    assert '"found_in": {"4": "verbatim"}' in judge.await_args.args[0]
    assert result["claim_grades"][0]["verdict"] == "unsupported"
