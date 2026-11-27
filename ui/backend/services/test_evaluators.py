"""Assertion evaluators for the admin evaluation harness.

One pure function per assertion type, each taking ``(assertion, actual_output)``
and returning an ``AssertionResult`` dict ``{type, passed, message, score}``.
Pure and side-effect free (so each is unit-testable in isolation) — the single
exception is ``llm_judge``, which receives an injected ``judge_fn`` callable so
the LLM call is mockable in tests and gated by config at the call site.

Output contracts (the runner builds these from the real capability calls):

- **search**: ``{"results": [{"id", "doc_id", "score", <fields>}, ...],
  "count": int}``. An expected id matches a result if it equals either the
  result's ``id`` or its ``doc_id``.
- **ai_summary**: ``{"summary": str, "usage": {...}}``.

A case passes only when every assertion passes; the case score is the minimum
assertion score (boolean assertions score 1.0/0.0, ``llm_judge`` scores 0–1).
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

AssertionResult = Dict[str, Any]
# A judge returns either a bare score, or a (score, reason) pair. The evaluator
# tolerates both so injected fakes and the real LLM judge are interchangeable.
JudgeFn = Callable[[str, str], Any]


class UnverifiedOverlapQuote(ValueError):
    """Safe to show in an evaluation result after both attempts fail."""

    def __init__(self):
        super().__init__(
            "The repetition judge could not verify its quoted text against both sections."
        )


def _result(
    atype: str, passed: bool, message: str, score: Optional[float] = None
) -> AssertionResult:
    if score is None:
        score = 1.0 if passed else 0.0
    return {
        "type": atype,
        "passed": bool(passed),
        "message": message,
        "score": float(score),
    }


def _id_pairs(output: Dict[str, Any]) -> List[Tuple[Optional[str], Optional[str]]]:
    """Return ``(id, doc_id)`` string pairs for each search result."""
    pairs: List[Tuple[Optional[str], Optional[str]]] = []
    for r in output.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        rid = None if r.get("id") is None else str(r.get("id"))
        did = None if r.get("doc_id") is None else str(r.get("doc_id"))
        pairs.append((rid, did))
    return pairs


def _matches(expected: Any, pairs: List[Tuple[Optional[str], Optional[str]]]) -> bool:
    e = str(expected)
    return any(e == rid or e == did for rid, did in pairs)


# ---------------------------------------------------------------------------
# Search assertions
# ---------------------------------------------------------------------------


def eval_result_contains_id(
    a: Dict[str, Any], output: Dict[str, Any]
) -> AssertionResult:
    expected = a.get("id")
    pairs = _id_pairs(output)
    passed = _matches(expected, pairs)
    verb = "found" if passed else "not found"
    return _result(
        "result_contains_id", passed, f"id {expected!r} {verb} in {len(pairs)} results"
    )


def eval_result_in_top_k(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    expected = a.get("id")
    k = int(a.get("k", 10))
    pairs = _id_pairs(output)[:k]
    passed = _matches(expected, pairs)
    verb = "in" if passed else "not in"
    return _result("result_in_top_k", passed, f"id {expected!r} {verb} top {k}")


def eval_min_results(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    value = int(a.get("value", a.get("min", 0)))
    count = len(output.get("results", []) or [])
    passed = count >= value
    return _result("min_results", passed, f"got {count} results, need >= {value}")


def eval_max_results(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    value = int(a.get("value", a.get("max", 0)))
    count = len(output.get("results", []) or [])
    passed = count <= value
    return _result("max_results", passed, f"got {count} results, need <= {value}")


def eval_ordering(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    expected = [str(x) for x in a.get("ids", [])]
    pairs = _id_pairs(output)
    positions: List[Optional[int]] = []
    for e in expected:
        idx = next(
            (i for i, (rid, did) in enumerate(pairs) if e == rid or e == did), None
        )
        positions.append(idx)
    missing = [expected[i] for i, p in enumerate(positions) if p is None]
    if missing:
        return _result("ordering", False, f"ids not found: {missing}")
    present = [p for p in positions if p is not None]
    passed = all(present[i] < present[i + 1] for i in range(len(present) - 1))
    verb = "matches" if passed else "violated"
    return _result("ordering", passed, f"relative order {verb}: {expected}")


def _field_value_ok(value: Any, expected: Any, mode: str) -> bool:
    if value is None:
        return False
    if mode == "equals":
        return str(value) == str(expected)
    return str(expected).lower() in str(value).lower()


def eval_field_match(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    field = a.get("field")
    mode = "equals" if "equals" in a else "contains"
    expected = a.get("equals", a.get("contains"))
    target_id = a.get("id")
    results = [r for r in (output.get("results", []) or []) if isinstance(r, dict)]
    if target_id is not None:
        t = str(target_id)
        results = [
            r for r in results if str(r.get("id")) == t or str(r.get("doc_id")) == t
        ]
    passed = any(_field_value_ok(r.get(field), expected, mode) for r in results)
    return _result(
        "field_match",
        passed,
        f"field {field!r} {mode} {expected!r}: {'yes' if passed else 'no'}",
    )


# ---------------------------------------------------------------------------
# AI summary assertions
# ---------------------------------------------------------------------------


def _summary_text(output: Dict[str, Any]) -> str:
    return str(output.get("summary", "") or "")


def _contains(text: str, needle: Any, case_insensitive: bool) -> bool:
    n = str(needle)
    if case_insensitive:
        return n.lower() in text.lower()
    return n in text


def eval_contains_text(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    text = a.get("text", "")
    ci = bool(a.get("case_insensitive", True))
    passed = _contains(_summary_text(output), text, ci)
    return _result(
        "contains_text", passed, f"text {text!r} {'present' if passed else 'absent'}"
    )


def eval_not_contains_text(
    a: Dict[str, Any], output: Dict[str, Any]
) -> AssertionResult:
    text = a.get("text", "")
    ci = bool(a.get("case_insensitive", True))
    passed = not _contains(_summary_text(output), text, ci)
    return _result(
        "not_contains_text",
        passed,
        f"text {text!r} {'absent' if passed else 'present'}",
    )


def eval_regex_match(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    pattern = a.get("pattern", "")
    flags = re.IGNORECASE if a.get("case_insensitive") else 0
    try:
        passed = re.search(pattern, _summary_text(output), flags) is not None
    except re.error as exc:
        return _result("regex_match", False, f"invalid regex: {exc}")
    return _result(
        "regex_match",
        passed,
        f"pattern {pattern!r} {'matched' if passed else 'no match'}",
    )


def eval_min_length(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    value = int(a.get("value", a.get("min", 0)))
    n = len(_summary_text(output))
    passed = n >= value
    return _result("min_length", passed, f"length {n} chars, need >= {value}")


def eval_max_length(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    value = int(a.get("value", a.get("max", 0)))
    n = len(_summary_text(output))
    passed = n <= value
    return _result("max_length", passed, f"length {n} chars, need <= {value}")


def eval_cites_source(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    source = str(a.get("source", a.get("doc_id", "")))
    ci = bool(a.get("case_insensitive", True))
    passed = bool(source) and _contains(_summary_text(output), source, ci)
    return _result(
        "cites_source",
        passed,
        f"source {source!r} {'cited' if passed else 'not cited'}",
    )


def eval_brief_length(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    target = (output.get("assignment") or {}).get("target_words")
    if not target:
        return _result("brief_length", False, "Set a word target on this case.")
    actual = output["words"]
    tolerance = float(a.get("tolerance", 0.15))
    passed = bool(output["written"] and abs(actual - target) <= target * tolerance)
    return _result(
        "brief_length",
        passed,
        f"{actual} of {target} requested words ({actual/target:.0%}). "
        f"Allowed difference: {tolerance:.0%}.",
    )


def eval_brief_paragraphs(a: Dict[str, Any], output: Dict[str, Any]) -> AssertionResult:
    from ui.backend.services.citation_fidelity import split_sentences

    text = _summary_text(output).strip()
    if not text:
        return _result("brief_paragraphs", False, "No section was written.")
    limit = a.get("max_percent", 50)
    if (
        not isinstance(limit, (int, float))
        or isinstance(limit, bool)
        or not 0 <= limit <= 100
    ):
        return _result("brief_paragraphs", False, "Set a percentage from 0 to 100.")
    counts = [len(split_sentences(p)) for p in re.split(r"\n\s*\n", text)]
    singles = counts.count(1)
    total = len(counts)
    return _result(
        "brief_paragraphs",
        total < 3 or singles * 100 <= limit * total,
        f"{singles} of {total} paragraphs have one sentence. "
        f"The {limit:g}% limit applies to sections with three or more paragraphs.",
    )


_STARTER_VOICE_RUBRIC = (
    "Check whether the voice, tone and language suit the requested reader. "
    "Quote wording from the section to explain the decision."
)


def brief_assertion_type(assertion):
    if (
        assertion["type"] == "llm_judge"
        and assertion.get("label") == "Relevance to the template and section"
    ):
        return "brief_relevance"
    if (
        assertion["type"] == "brief_writing"
        and assertion.get("rubric") == _STARTER_VOICE_RUBRIC
    ):
        return "brief_voice"
    return assertion["type"]


def judge_rubric_key(assertion: Dict[str, Any]) -> str:
    rubric = str(assertion.get("rubric", ""))
    if assertion.get("type") in ("brief_writing", "brief_factual", "brief_relevance"):
        return json.dumps([assertion["type"], rubric])
    return rubric


def eval_llm_judge(
    a: Dict[str, Any], output: Dict[str, Any], judge_fn: Optional[JudgeFn] = None
) -> AssertionResult:
    if judge_fn is None:
        return _result("llm_judge", False, "llm_judge is disabled", score=0.0)
    rubric = str(a.get("rubric", ""))
    threshold = float(a.get("threshold", 1.0))
    verdict = judge_fn(_summary_text(output), judge_rubric_key(a))
    prompt = ""
    if isinstance(verdict, tuple):
        score = verdict[0]
        reason = verdict[1] if len(verdict) > 1 else ""
        prompt = verdict[2] if len(verdict) > 2 else ""
    else:
        score, reason = verdict, ""
    score = max(0.0, min(1.0, float(score)))
    passed = score >= threshold
    # Message is just the judge's reason — the score/pass are shown separately,
    # so don't duplicate them here.
    message = reason or "(no reason provided)"
    result = _result(str(a.get("type", "llm_judge")), passed, message, score=score)
    # Surface the rubric + the exact prompt the judge was given (shown per run).
    result["rubric"] = rubric
    if a.get("label"):
        result["label"] = a["label"]
    if rubric == "brief_overlap" and isinstance(verdict, tuple) and len(verdict) == 4:
        result["repetitions"] = verdict[3]["repetitions"]
    if isinstance(verdict, tuple) and len(verdict) == 4 and "relevance" in verdict[3]:
        result["relevance"] = verdict[3]["relevance"]
    if prompt:
        result["judge_prompt"] = prompt
    return result


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_EVALUATORS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], AssertionResult]] = {
    "brief_length": eval_brief_length,
    "brief_paragraphs": eval_brief_paragraphs,
    "result_contains_id": eval_result_contains_id,
    "result_in_top_k": eval_result_in_top_k,
    "min_results": eval_min_results,
    "max_results": eval_max_results,
    "ordering": eval_ordering,
    "field_match": eval_field_match,
    "contains_text": eval_contains_text,
    "not_contains_text": eval_not_contains_text,
    "regex_match": eval_regex_match,
    "min_length": eval_min_length,
    "max_length": eval_max_length,
    "cites_source": eval_cites_source,
}

VALID_ASSERTION_TYPES = set(_EVALUATORS) | {
    "brief_voice",
    "brief_factual",
    "brief_relevance",
    "llm_judge",
    "brief_overlap",
    "brief_intro_scope",
    "brief_writing",
    "brief_structure",
}


def _factual_result(assertion, output, judge_fn):
    rubric = str(assertion["rubric"])
    info = {"type": "brief_factual", "rubric": rubric}
    if assertion.get("label"):
        info["label"] = assertion["label"]
    if not output["written"]:
        return {**_result("brief_factual", False, "No section was written."), **info}
    if judge_fn is None:
        return {
            **_result("brief_factual", False, "The factual support judge is disabled."),
            **info,
        }
    grades, prompt = judge_fn(_summary_text(output), judge_rubric_key(info))
    threshold = float(assertion.get("threshold", 1.0))
    errors = [f"Claim {g['claim']}: {g['reason']}" for g in grades if g.get("error")]
    assessed = [
        (
            g
            if g.get("error")
            else {
                **g,
                "passed": not g.get("evidence_failed") and g["score"] >= threshold,
            }
        )
        for g in grades
    ]
    if errors:
        return {
            **info,
            "error": True,
            "message": " ".join(errors),
            "judge_prompt": prompt,
            "claim_grades": assessed,
        }
    score = min(g["score"] for g in grades)
    return {
        **info,
        "score": score,
        "passed": all(g["passed"] for g in assessed),
        "message": "",
        "judge_prompt": prompt,
        "claim_grades": assessed,
    }


def evaluate_assertion(
    assertion: Dict[str, Any],
    output: Dict[str, Any],
    judge_fn: Optional[JudgeFn] = None,
) -> AssertionResult:
    """Evaluate a single assertion against ``output``."""
    atype = brief_assertion_type(assertion) if assertion.get("type") else None
    from ui.backend.services.brief_experiment_claims import is_factual_criterion

    if output.get("capability") == "brief" and is_factual_criterion(assertion):
        return _factual_result(assertion, output, judge_fn)
    if atype == "brief_voice":
        if not (output.get("assignment") or {}).get("voice_profile"):
            return _result(
                atype, True, "No voice and tone profile was selected.", score=1.0
            )
        result = eval_llm_judge(
            {**assertion, "type": atype, "rubric": atype}, output, judge_fn
        )
        return {
            **result,
            "rubric": "Does the section follow the selected voice and tone profile?",
        }
    if atype == "brief_structure":
        from ui.backend.services.brief_experiment import structure_result

        return structure_result(output)
    if atype in ("brief_overlap", "brief_intro_scope"):
        result = eval_llm_judge({"rubric": atype}, output, judge_fn)
        return {
            **result,
            "type": atype,
            "rubric": (
                "Does the introduction leave details to its subheadings?"
                if atype == "brief_intro_scope"
                else "Does this section repeat a finding from another section?"
            ),
        }
    if atype in ("llm_judge", "brief_writing", "brief_relevance"):
        return eval_llm_judge(assertion, output, judge_fn=judge_fn)
    fn = _EVALUATORS.get(str(atype))
    if fn is None:
        return _result(
            str(atype), False, f"unknown assertion type: {atype!r}", score=0.0
        )
    return fn(assertion, output)


def evaluate_assertions(
    assertions: List[Dict[str, Any]],
    output: Dict[str, Any],
    judge_fn: Optional[JudgeFn] = None,
) -> Tuple[List[AssertionResult], bool, float]:
    """Evaluate all assertions; return ``(results, all_passed, min_score)``.

    With no assertions, the case trivially passes with score 1.0.
    """
    results = [evaluate_assertion(a, output, judge_fn=judge_fn) for a in assertions]
    all_passed = all(r.get("passed") for r in results) if results else True
    min_score = min((r.get("score", 0.0) for r in results), default=1.0)
    return results, all_passed, min_score
