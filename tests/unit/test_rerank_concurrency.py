"""Concurrency limits for reranking.

A local reranker runs the model inside the API process, so several at once
multiply resident memory and have OOM-killed the API. A hosted reranker
(Azure Foundry, Google Vertex) is an HTTP call and carries no such cost, but
both shared one limit, which serialised every reranked search in deployments
that rerank remotely. These tests pin the two apart.
"""

import threading
import time
from unittest.mock import patch

import pytest

from ui.backend.services import search_models


@pytest.mark.unit
def test_remote_rerank_limit_when_defaulted_then_higher_than_local():
    assert search_models.MAX_CONCURRENT_RERANKS == 1
    assert search_models.MAX_CONCURRENT_REMOTE_RERANKS > 1


class _OverlapProbe:
    """Records whether two calls were ever in flight at the same time."""

    def __init__(self, hold: float = 0.2):
        self._hold = hold
        self._active = 0
        self._lock = threading.Lock()
        self.overlapped = False

    def __call__(self, *_args, **_kwargs):
        with self._lock:
            self._active += 1
            if self._active > 1:
                self.overlapped = True
        time.sleep(self._hold)
        with self._lock:
            self._active -= 1
        return [1.0]


def _call_twice(target) -> None:
    """Invoke target on two threads and wait for both.

    Patching happens in the caller, once, before the threads start: two
    threads entering the same ``patch.object`` would restore each other's
    mocks out of order and leave one installed for the rest of the session.
    """
    threads = [threading.Thread(target=target) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _score_once(**overrides):
    kwargs = {
        "query": "q",
        "documents": ["d"],
        "rerank_model": "m",
        "rerank_config": {},
        "model_name": "m",
        "supported_rerank_models": {},
        "rerank_model_loader": None,
    }
    kwargs.update(overrides)
    return lambda: search_models._compute_rerank_scores(**kwargs)


@pytest.mark.unit
def test_vertex_rerank_when_two_requests_then_they_overlap():
    probe = _OverlapProbe()
    with patch.object(
        search_models, "_rerank_via_vertex_with_fallback", new=probe
    ), patch.object(search_models, "_is_google_vertex_reranker", return_value=True):
        _call_twice(
            _score_once(
                rerank_model="vertex-ai-ranker",
                rerank_config={"provider": "google_vertex", "model_id": "m"},
            )
        )

    assert probe.overlapped, (
        "Hosted reranker calls were serialised; they should be bounded by "
        "MAX_CONCURRENT_REMOTE_RERANKS, not the single-slot local limit."
    )


@pytest.mark.unit
def test_local_rerank_when_two_requests_then_they_are_serialised():
    probe = _OverlapProbe()

    class _Reranker:
        def rerank(self, query, documents):
            return probe(query, documents)

    with patch.object(
        search_models, "_is_google_vertex_reranker", return_value=False
    ), patch.object(search_models, "_is_azure_foundry_reranker", return_value=False):
        _call_twice(
            _score_once(
                rerank_model="local",
                model_name="local",
                rerank_model_loader=lambda _m: _Reranker(),
            )
        )

    assert not probe.overlapped, (
        "Local reranker inference overlapped; it must stay serialised, "
        "because concurrent in-process inference has OOM-killed the API."
    )


@pytest.mark.unit
def test_module_state_when_tests_finish_then_vertex_helper_is_not_a_mock():
    """Catches the patch-restore hazard the helper above documents."""
    assert "Mock" not in type(search_models._rerank_via_vertex_with_fallback).__name__
