from pipeline.orchestrator import core_processing


class DummyDB:
    def __init__(self, doc=None):
        self._doc = doc
        self.client = self
        self.documents_collection = "documents"

    def get_document(self, doc_id):
        return self._doc

    def set_payload(self, *_args, **_kwargs):
        return None


class DummyOrchestrator:
    def __init__(self):
        self.skip_parse = False
        self.skip_summarize = False
        self.skip_tag = False
        self.skip_index = False
        self.doc_id = None
        self.db = DummyDB()
        self.report = None
        self.recent_first = False
        self.partition = False
        self.partition_num = None
        self.partition_total = None
        self.data_source = "uneg"
        self.save_chunks = False
        self.pipeline_config = {}


def test_build_processing_steps_respects_skip_flags():
    orchestrator = DummyOrchestrator()
    orchestrator.skip_summarize = True
    orchestrator.skip_index = True

    steps = core_processing._build_processing_steps(orchestrator)

    assert steps == ["Parse", "Tag"]


def test_collect_documents_returns_doc_when_found():
    orchestrator = DummyOrchestrator()
    orchestrator.doc_id = "doc-1"
    orchestrator.db = DummyDB(doc={"title": "Doc"})

    docs = core_processing._collect_documents(orchestrator)

    assert docs == [{"title": "Doc", "id": "doc-1"}]


def test_collect_documents_returns_empty_when_missing():
    orchestrator = DummyOrchestrator()
    orchestrator.doc_id = "doc-404"
    orchestrator.db = DummyDB(doc=None)

    docs = core_processing._collect_documents(orchestrator)

    assert docs == []


def test_process_docs_sequential_counts_results(monkeypatch):
    orchestrator = DummyOrchestrator()
    stats = {"processed": 0, "success": 0, "failed": 0}
    docs = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    def fake_init_worker(*_args, **_kwargs):
        return None

    results = [
        {"stages": {"parse": {"success": True}}},
        {"stages": {"parse": {"success": False}}},
        {"error": "boom"},
    ]

    def fake_process_document_wrapper(_doc):
        return results.pop(0)

    monkeypatch.setattr(core_processing, "init_worker", fake_init_worker)
    monkeypatch.setattr(
        core_processing, "process_document_wrapper", fake_process_document_wrapper
    )

    core_processing._process_docs_sequential(orchestrator, docs, stats)

    assert stats == {"processed": 3, "success": 1, "failed": 2}
