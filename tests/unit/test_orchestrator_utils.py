from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import pipeline.orchestrator.worker as orchestrator


def _memory_available_gb(gb: int):
    return SimpleNamespace(available=gb * 1024 * 1024 * 1024)


def test_process_document_wrapper_returns_error_without_db(monkeypatch):
    monkeypatch.setattr(orchestrator, "_worker_context", {})
    monkeypatch.setattr(
        orchestrator.psutil, "virtual_memory", lambda: _memory_available_gb(4)
    )

    result = orchestrator.process_document_wrapper({"id": "doc-1", "title": "Title"})

    assert result == {"error": "Worker not initialized"}


def test_process_document_wrapper_times_out_on_low_memory(monkeypatch):
    monkeypatch.setattr(orchestrator, "_worker_context", {"db": MagicMock()})
    monkeypatch.setattr(
        orchestrator.psutil, "virtual_memory", lambda: _memory_available_gb(0)
    )
    monkeypatch.setattr(orchestrator.random, "uniform", lambda *_: 0)
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_: None)

    times = iter([0, 601])
    monkeypatch.setattr(orchestrator.time, "time", lambda: next(times))

    result = orchestrator.process_document_wrapper({"id": "doc-2", "title": "Title"})

    assert result == {"error": "OOM Protection: Timeout waiting for memory"}


def test_process_document_wrapper_returns_basic_result(monkeypatch):
    monkeypatch.setattr(orchestrator, "_worker_context", {"db": MagicMock()})
    monkeypatch.setattr(
        orchestrator.psutil, "virtual_memory", lambda: _memory_available_gb(4)
    )

    result = orchestrator.process_document_wrapper({"id": "doc-3", "map_title": "Doc"})

    assert result["doc_id"] == "doc-3"
    assert result["title"] == "Doc"
    assert result["stages"] == {}


def test_generate_processing_log_skips_missing_folder(monkeypatch):
    monkeypatch.setattr(
        orchestrator.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess.run should not be called"),
    )

    orchestrator._generate_processing_log("doc-4", None)
