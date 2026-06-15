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

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

AssertionResult = Dict[str, Any]
# A judge returns either a bare score, or a (score, reason) pair. The evaluator
# tolerates both so injected fakes and the real LLM judge are interchangeable.
JudgeFn = Callable[[str, str], Any]


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


def eval_llm_judge(
    a: Dict[str, Any], output: Dict[str, Any], judge_fn: Optional[JudgeFn] = None
) -> AssertionResult:
    if judge_fn is None:
        return _result("llm_judge", False, "llm_judge is disabled", score=0.0)
    rubric = str(a.get("rubric", ""))
    threshold = float(a.get("threshold", 1.0))
    verdict = judge_fn(_summary_text(output), rubric)
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
    result = _result("llm_judge", passed, message, score=score)
    # Surface the rubric + the exact prompt the judge was given (shown per run).
    result["rubric"] = rubric
    if prompt:
        result["judge_prompt"] = prompt
    return result


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_EVALUATORS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], AssertionResult]] = {
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

VALID_ASSERTION_TYPES = set(_EVALUATORS) | {"llm_judge"}


def evaluate_assertion(
    assertion: Dict[str, Any],
    output: Dict[str, Any],
    judge_fn: Optional[JudgeFn] = None,
) -> AssertionResult:
    """Evaluate a single assertion against ``output``."""
    atype = assertion.get("type")
    if atype == "llm_judge":
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
    all_passed = all(r["passed"] for r in results) if results else True
    min_score = min((r["score"] for r in results), default=1.0)
    return results, all_passed, min_score
