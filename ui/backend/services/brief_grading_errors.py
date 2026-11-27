"""Explain which Brief checks errored and which returned a failing grade."""

from pydantic import ValidationError

from ui.backend.services.test_evaluators import UnverifiedOverlapQuote

_CHECK_NAMES = {
    "brief_overlap": "Cross-section repetition",
    "brief_intro_scope": "Introduction scope",
    "brief_factual": "Factual support from citations",
    "brief_writing": "Writing quality",
    "brief_voice": "Selected voice and tone profile",
    "brief_structure": "Format and citations",
    "brief_length": "Word count",
    "brief_paragraphs": "One-sentence paragraphs",
    "llm_judge": "Custom grading criterion",
}


def grading_error_reason(exc):
    if isinstance(exc, UnverifiedOverlapQuote):
        return str(exc)
    if isinstance(exc, ValidationError):
        return "The judge returned a response that did not match the required grading format."
    if isinstance(exc, TimeoutError):
        return "The judge timed out before returning a grade."
    return "The check ended before it could return a grade."


def _check_name(check):
    return check.get("label") or _CHECK_NAMES.get(check["type"], check["type"])


def _failed_check(check):
    numbers = [
        str(g["claim"])
        for g in check.get("claim_grades", [])
        if g.get("passed") is False
    ]
    if not numbers:
        return _check_name(check)
    noun = "claim" if len(numbers) == 1 else "claims"
    return f"{_check_name(check)} ({noun} {', '.join(numbers)})"


def brief_grading_error(checks):
    errors = [
        f"{_check_name(check)}: {check['message']}"
        for check in checks
        if check.get("error")
    ]
    if not errors:
        return None
    failed = [
        _failed_check(c)
        for c in checks
        if c.get("passed") is False and not c.get("error")
    ]
    if failed:
        errors.append(f"Also failed: {'; '.join(failed)}.")
    return " ".join(errors)
