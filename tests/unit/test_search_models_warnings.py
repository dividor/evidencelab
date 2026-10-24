"""Reranker fallback is reported to whoever is collecting search warnings."""

from types import SimpleNamespace

import pytest

from ui.backend.services import search_models

pytestmark = pytest.mark.unit


def _results(n):
    return [
        SimpleNamespace(id=str(i), payload={"text": f"t{i}"}, score=1.0)
        for i in range(n)
    ]


def test_rerank_results_notes_warning_when_reranker_unavailable(monkeypatch):
    monkeypatch.setattr(search_models, "_compute_rerank_scores", lambda **kw: None)
    notes = []
    token = search_models.search_warnings.set(notes)
    try:
        out = search_models.rerank_results(
            "q", _results(3), rerank_model="vertex-ai-ranker"
        )
    finally:
        search_models.search_warnings.reset(token)
    assert [r.id for r in out] == ["0", "1", "2"]  # original order kept
    assert len(notes) == 1
    assert "vertex-ai-ranker" in notes[0] and "unreranked" in notes[0]


def test_rerank_results_without_collector_only_logs(monkeypatch):
    monkeypatch.setattr(search_models, "_compute_rerank_scores", lambda **kw: None)
    assert search_models.search_warnings.get() is None
    out = search_models.rerank_results(
        "q", _results(2), rerank_model="vertex-ai-ranker"
    )
    assert len(out) == 2


def test_note_search_warning_is_noop_without_collector():
    search_models.note_search_warning("ignored")  # must not raise
