"""Tests for _apply_min_score_filter — the in-doc PDF search relevance floor
with exact-match exemption."""

from types import SimpleNamespace

import pytest

from ui.backend.routes.search import _apply_min_score_filter


def _result(score: float, text: str) -> SimpleNamespace:
    """Mock SearchResult-shaped object with score + text."""
    return SimpleNamespace(score=score, text=text)


@pytest.mark.unit
def test_drops_results_below_min_score_when_no_exact_match():
    results = [
        _result(0.8, "highly relevant chunk"),
        _result(0.4, "moderately relevant"),
        _result(0.2, "barely relevant"),
    ]
    out = _apply_min_score_filter(
        results, min_score=0.5, include_exact_matches=False, query="ANYTHING"
    )
    assert len(out) == 1
    assert out[0].score == 0.8


@pytest.mark.unit
def test_min_score_zero_is_a_no_op():
    results = [_result(0.1, "low"), _result(0.05, "lower")]
    out = _apply_min_score_filter(
        results, min_score=0.0, include_exact_matches=True, query="any"
    )
    assert len(out) == 2


@pytest.mark.unit
def test_exact_match_chunks_bypass_the_cutoff_when_flag_is_true():
    """Chunks containing the query as a verbatim substring should pass even
    if their relevance score is below min_score. This is the core behavior
    the in-doc PDF search relies on."""
    results = [
        _result(0.8, "high score; no literal match"),
        _result(0.3, "this paragraph mentions monsoon flooding directly"),
        _result(0.2, "low score; no literal match"),
    ]
    out = _apply_min_score_filter(
        results,
        min_score=0.5,
        include_exact_matches=True,
        query="monsoon flooding",
    )
    # 0.8 passes by score; 0.3 passes by exact match; 0.2 fails both.
    assert len(out) == 2
    assert out[0].score == 0.8
    assert out[1].score == 0.3


@pytest.mark.unit
def test_exact_match_is_case_insensitive():
    results = [_result(0.1, "WFP responded to the El Niño event in 2015")]
    out = _apply_min_score_filter(
        results, min_score=0.7, include_exact_matches=True, query="el niño"
    )
    assert len(out) == 1


@pytest.mark.unit
def test_include_exact_matches_disabled_drops_low_scoring_literal_hits():
    """When the flag is off, low-scoring chunks are dropped even if they
    contain the query verbatim — preserves the simpler "score-only" semantics
    for callers that want it."""
    results = [_result(0.1, "this paragraph mentions monsoon flooding directly")]
    out = _apply_min_score_filter(
        results,
        min_score=0.5,
        include_exact_matches=False,
        query="monsoon flooding",
    )
    assert len(out) == 0


@pytest.mark.unit
def test_empty_query_does_not_match_anything_via_exact_path():
    """An empty / whitespace-only query must NOT trigger the exact-match
    exemption (otherwise every chunk would match the empty substring)."""
    results = [_result(0.1, "any text"), _result(0.2, "more text")]
    out = _apply_min_score_filter(
        results, min_score=0.5, include_exact_matches=True, query="   "
    )
    assert len(out) == 0


@pytest.mark.unit
def test_handles_results_with_missing_or_none_text():
    results = [
        _result(0.1, None),
        _result(0.2, ""),
        _result(0.9, "high score"),
    ]
    out = _apply_min_score_filter(
        results, min_score=0.5, include_exact_matches=True, query="anything"
    )
    # Only the 0.9 passes — the others have no text and low scores.
    assert len(out) == 1
    assert out[0].score == 0.9


@pytest.mark.unit
def test_treats_none_score_as_zero():
    r = SimpleNamespace(score=None, text="some content")
    out = _apply_min_score_filter(
        [r], min_score=0.5, include_exact_matches=False, query="x"
    )
    assert len(out) == 0
