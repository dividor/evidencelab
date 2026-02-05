from unittest.mock import MagicMock

import pytest

from pipeline.utilities import tasks


def test_reprocess_document_runs_orchestrator(monkeypatch):
    mock_db = MagicMock()

    def fake_get_db(_):
        return mock_db

    created = {}

    class DummyOrchestrator:
        def __init__(self, **kwargs):
            created["kwargs"] = kwargs

        def run(self):
            created["ran"] = True

    monkeypatch.setattr("pipeline.db.get_db", fake_get_db)
    monkeypatch.setattr("pipeline.orchestrator.PipelineOrchestrator", DummyOrchestrator)

    monkeypatch.setattr(tasks.reprocess_document, "update_state", MagicMock())

    result = tasks.reprocess_document.run(
        doc_id="doc-1", filepath="/tmp/doc.pdf", data_source="uneg"
    )

    assert result["success"] is True
    assert created["ran"] is True
    mock_db.update_document.assert_any_call("doc-1", {"is_duplicate": False})
    mock_db.update_document.assert_any_call(
        "doc-1", {"sys_status": "downloaded"}, wait=True
    )


def test_reprocess_document_updates_error_state(monkeypatch):
    mock_db = MagicMock()

    def fake_get_db(_):
        return mock_db

    class DummyOrchestrator:
        def __init__(self, **kwargs):
            pass

        def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("pipeline.db.get_db", fake_get_db)
    monkeypatch.setattr("pipeline.orchestrator.PipelineOrchestrator", DummyOrchestrator)

    with pytest.raises(RuntimeError):
        tasks.reprocess_document.run(
            doc_id="doc-2", filepath="/tmp/doc.pdf", data_source="uneg"
        )

    mock_db.update_document.assert_any_call(
        "doc-2", {"sys_status": "error", "sys_error_message": "boom"}
    )


def test_reprocess_document_toc_returns_not_found(monkeypatch):
    mock_db = MagicMock()
    mock_db.get_document.return_value = None

    monkeypatch.setattr("pipeline.db.get_db", lambda _: mock_db)

    result = tasks.reprocess_document_toc.run(doc_id="doc-404")

    assert result == {"success": False, "message": "Document not found"}


def test_reprocess_document_toc_success(monkeypatch):
    class FakeSectionTypeTagger:
        def __init__(self):
            self._document_cache = {"doc-1": {"cached": True}}

        def classify_document_toc(self, doc):
            return ["tag-1", "tag-2"]

    class FakeTaggerProcessor:
        def __init__(self, data_source):
            self.data_source = data_source
            self._taggers = [FakeSectionTypeTagger()]

        def setup(self):
            self.setup_called = True

        def tag_chunks_only(self, doc):
            self.tagged_doc = doc

    mock_db = MagicMock()
    mock_db.get_document.side_effect = [
        {"id": "doc-1", "sys_toc": ["A"], "sys_toc_classified": ""},
        {"id": "doc-1", "sys_toc_classified": "classified"},
    ]

    monkeypatch.setattr("pipeline.db.get_db", lambda _: mock_db)
    monkeypatch.setattr(
        "pipeline.processors.tagging.tagger.SectionTypeTagger", FakeSectionTypeTagger
    )
    monkeypatch.setattr(
        "pipeline.processors.tagging.tagger.TaggerProcessor", FakeTaggerProcessor
    )

    result = tasks.reprocess_document_toc.run(doc_id="doc-1")

    assert result["success"] is True
    assert result["sys_toc_classified"] == "classified"
    assert "Reprocessed TOC with 2 classifications" in result["message"]
