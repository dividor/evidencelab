"""Unit tests for the evaluation-harness assertion evaluators.

Exercises the real evaluator functions (no reimplementation of assertion
logic): pass + fail for every assertion type, plus dispatch, the injected
llm_judge, and the all-pass / min-score aggregation.
"""

import pytest

from ui.backend.services import test_evaluators as ev

pytestmark = pytest.mark.unit


def _search_output(*ids):
    return {
        "results": [
            {"id": f"c{i}", "doc_id": d, "score": 1.0 - i * 0.1}
            for i, d in enumerate(ids)
        ],
        "count": len(ids),
    }


def _summary_output(text):
    return {"summary": text, "usage": {}}


class TestSearchAssertions:
    def test_result_contains_id_when_present_then_passes(self):
        out = _search_output("A", "B", "C")
        assert ev.eval_result_contains_id({"id": "B"}, out)["passed"] is True

    def test_result_contains_id_when_absent_then_fails(self):
        out = _search_output("A", "B")
        res = ev.eval_result_contains_id({"id": "Z"}, out)
        assert res["passed"] is False and res["score"] == 0.0

    def test_result_in_top_k_when_outside_k_then_fails(self):
        out = _search_output("A", "B", "C")  # C is index 2
        assert ev.eval_result_in_top_k({"id": "C", "k": 2}, out)["passed"] is False

    def test_result_in_top_k_when_inside_k_then_passes(self):
        out = _search_output("A", "B", "C")
        assert ev.eval_result_in_top_k({"id": "C", "k": 3}, out)["passed"] is True

    def test_min_results_when_too_few_then_fails(self):
        assert (
            ev.eval_min_results({"value": 5}, _search_output("A", "B"))["passed"]
            is False
        )

    def test_min_results_when_enough_then_passes(self):
        assert (
            ev.eval_min_results({"value": 2}, _search_output("A", "B"))["passed"]
            is True
        )

    def test_max_results_when_too_many_then_fails(self):
        assert (
            ev.eval_max_results({"value": 1}, _search_output("A", "B"))["passed"]
            is False
        )

    def test_ordering_when_subset_in_order_then_passes(self):
        out = _search_output("A", "B", "C", "D")
        assert ev.eval_ordering({"ids": ["A", "C"]}, out)["passed"] is True

    def test_ordering_when_subset_out_of_order_then_fails(self):
        out = _search_output("A", "B", "C")
        assert ev.eval_ordering({"ids": ["C", "A"]}, out)["passed"] is False

    def test_ordering_when_id_missing_then_fails(self):
        out = _search_output("A", "B")
        res = ev.eval_ordering({"ids": ["A", "Z"]}, out)
        assert res["passed"] is False and "not found" in res["message"]

    def test_field_match_equals_when_matching_then_passes(self):
        out = {"results": [{"id": "c0", "doc_id": "A", "organization": "WFP"}]}
        assert (
            ev.eval_field_match({"field": "organization", "equals": "WFP"}, out)[
                "passed"
            ]
            is True
        )

    def test_field_match_contains_when_substring_then_passes(self):
        out = {"results": [{"id": "c0", "doc_id": "A", "title": "Climate Resilience"}]}
        assert (
            ev.eval_field_match({"field": "title", "contains": "climate"}, out)[
                "passed"
            ]
            is True
        )

    def test_field_match_when_no_field_then_fails(self):
        out = {"results": [{"id": "c0", "doc_id": "A"}]}
        assert (
            ev.eval_field_match({"field": "missing", "equals": "x"}, out)["passed"]
            is False
        )


class TestSummaryAssertions:
    def test_contains_text_case_insensitive_then_passes(self):
        out = _summary_output("The Outcome was positive.")
        assert ev.eval_contains_text({"text": "outcome"}, out)["passed"] is True

    def test_contains_text_case_sensitive_when_mismatch_then_fails(self):
        out = _summary_output("The Outcome was positive.")
        res = ev.eval_contains_text({"text": "outcome", "case_insensitive": False}, out)
        assert res["passed"] is False

    def test_not_contains_text_when_absent_then_passes(self):
        out = _summary_output("All good.")
        assert ev.eval_not_contains_text({"text": "error"}, out)["passed"] is True

    def test_not_contains_text_when_present_then_fails(self):
        out = _summary_output("An error occurred.")
        assert ev.eval_not_contains_text({"text": "error"}, out)["passed"] is False

    def test_regex_match_when_pattern_matches_then_passes(self):
        out = _summary_output("Score: 87%")
        assert ev.eval_regex_match({"pattern": r"\d+%"}, out)["passed"] is True

    def test_regex_match_when_invalid_pattern_then_fails_gracefully(self):
        res = ev.eval_regex_match({"pattern": "("}, _summary_output("x"))
        assert res["passed"] is False and "invalid regex" in res["message"]

    def test_min_length_when_too_short_then_fails(self):
        assert (
            ev.eval_min_length({"value": 100}, _summary_output("short"))["passed"]
            is False
        )

    def test_max_length_when_within_then_passes(self):
        assert (
            ev.eval_max_length({"value": 100}, _summary_output("short"))["passed"]
            is True
        )

    def test_cites_source_when_present_then_passes(self):
        out = _summary_output("See report DOC-123 for details.")
        assert ev.eval_cites_source({"source": "DOC-123"}, out)["passed"] is True

    def test_cites_source_when_absent_then_fails(self):
        out = _summary_output("No citations here.")
        assert ev.eval_cites_source({"source": "DOC-999"}, out)["passed"] is False


class TestLlmJudge:
    def test_llm_judge_when_disabled_then_fails(self):
        res = ev.eval_llm_judge(
            {"rubric": "good?", "threshold": 0.7}, _summary_output("x")
        )
        assert res["passed"] is False and res["score"] == 0.0

    def test_llm_judge_uses_injected_score_and_threshold(self):
        out = _summary_output("great summary")
        res = ev.eval_llm_judge(
            {"rubric": "quality", "threshold": 0.8},
            out,
            judge_fn=lambda text, rubric: 0.9,
        )
        assert res["passed"] is True and res["score"] == 0.9

    def test_llm_judge_below_threshold_then_fails(self):
        res = ev.eval_llm_judge(
            {"rubric": "q", "threshold": 0.8},
            _summary_output("x"),
            judge_fn=lambda t, r: 0.5,
        )
        assert res["passed"] is False and res["score"] == 0.5

    def test_llm_judge_clamps_out_of_range_score(self):
        res = ev.eval_llm_judge(
            {"rubric": "q", "threshold": 0.5},
            _summary_output("x"),
            judge_fn=lambda t, r: 5.0,
        )
        assert res["score"] == 1.0

    def test_llm_judge_includes_reason_from_tuple_verdict(self):
        res = ev.eval_llm_judge(
            {"rubric": "q", "threshold": 0.5},
            _summary_output("x"),
            judge_fn=lambda t, r: (0.8, "covers the key points"),
        )
        assert res["passed"] is True and res["score"] == 0.8
        assert "covers the key points" in res["message"]

    def test_llm_judge_result_includes_rubric(self):
        res = ev.eval_llm_judge(
            {"rubric": "must cite Kenya", "threshold": 0.5},
            _summary_output("x"),
            judge_fn=lambda t, r: (0.6, "ok"),
        )
        assert res["rubric"] == "must cite Kenya"

    def test_llm_judge_default_threshold_is_one(self):
        # No threshold given -> defaults to 1.0, so a 0.9 score fails.
        res = ev.eval_llm_judge(
            {"rubric": "q"}, _summary_output("x"), judge_fn=lambda t, r: 0.9
        )
        assert res["passed"] is False


class TestDispatchAndAggregation:
    def test_evaluate_assertion_unknown_type_then_fails(self):
        res = ev.evaluate_assertion({"type": "nope"}, _summary_output("x"))
        assert res["passed"] is False and "unknown assertion type" in res["message"]

    def test_evaluate_assertion_routes_llm_judge_with_judge_fn(self):
        res = ev.evaluate_assertion(
            {"type": "llm_judge", "threshold": 0.5},
            _summary_output("x"),
            judge_fn=lambda t, r: 0.6,
        )
        assert res["type"] == "llm_judge" and res["passed"] is True

    def test_evaluate_assertions_all_pass_then_min_score_one(self):
        out = _summary_output("contains outcome and result")
        results, passed, score = ev.evaluate_assertions(
            [
                {"type": "contains_text", "text": "outcome"},
                {"type": "min_length", "value": 1},
            ],
            out,
        )
        assert passed is True and score == 1.0 and len(results) == 2

    def test_evaluate_assertions_one_fail_then_not_passed(self):
        out = _summary_output("short")
        _results, passed, score = ev.evaluate_assertions(
            [
                {"type": "contains_text", "text": "missing"},
                {"type": "min_length", "value": 1},
            ],
            out,
        )
        assert passed is False and score == 0.0

    def test_evaluate_assertions_empty_then_passes(self):
        _results, passed, score = ev.evaluate_assertions([], _summary_output("x"))
        assert passed is True and score == 1.0
