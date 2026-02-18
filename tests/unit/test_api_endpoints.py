import sys
from collections import Counter
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ui.backend import main as main_module
from ui.backend.routes import search as search_module
from ui.backend.utils import facet_helpers as facet_module
from ui.backend.utils.language_codes import LANGUAGE_CODES, LANGUAGE_NAMES


def _make_request(method: str = "GET", path: str = "/", query: str = "") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query.encode("utf-8"),
        "headers": [],
        "client": ("testclient", 1234),
        "app": main_module.app,
    }
    return Request(scope)


def _make_search_result(chunk_id: str = "c1") -> main_module.SearchResult:
    return main_module.SearchResult(
        chunk_id=chunk_id,
        doc_id="doc-1",
        text="Sample text",
        page_num=1,
        headings=["Intro"],
        score=0.9,
        title="Sample",
    )


@pytest.mark.asyncio
async def test_translate_success(monkeypatch):
    async def fake_translate(
        text: str, target_language: str, source_language: str | None = None
    ) -> str:
        return f"{text}-{target_language}"

    llm_module = ModuleType("llm_service")
    llm_module.translate_text = fake_translate
    monkeypatch.setitem(sys.modules, "llm_service", llm_module)

    request = _make_request(method="POST", path="/translate")
    body = main_module.TranslateRequest(text="hello", target_language="fr")
    result = await main_module.translate(request, body)

    assert result == {"translated_text": "hello-fr"}


@pytest.mark.asyncio
async def test_translate_error(monkeypatch):
    async def fake_translate(
        text: str, target_language: str, source_language: str | None = None
    ) -> str:
        raise RuntimeError("boom")

    llm_module = ModuleType("llm_service")
    llm_module.translate_text = fake_translate
    monkeypatch.setitem(sys.modules, "llm_service", llm_module)

    request = _make_request(method="POST", path="/translate")
    body = main_module.TranslateRequest(text="hello", target_language="fr")
    with pytest.raises(HTTPException) as exc:
        await main_module.translate(request, body)

    assert exc.value.status_code == 500


def test_root_endpoint():
    result = main_module.root(_make_request())
    assert result["name"] == "Humanitarian Evaluation Search API"
    assert "/search" in result["endpoints"]


def test_config_models(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "DB_VECTORS",
        {
            "model_a": {"enabled": True, "source": "huggingface"},
            "model_b": {"enabled": False, "source": "huggingface"},
        },
    )
    monkeypatch.setattr(main_module, "DENSE_VECTOR_NAME", "model_a")

    models = main_module.get_config_models()

    assert len(models) == 1
    assert models[0].name == "model_a"
    assert models[0].is_default is True


def test_config_llms(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "SUPPORTED_LLMS",
        {
            "llm_a": {"model": "A", "provider": "huggingface"},
            "llm_b": {"model": "B", "provider": "azure"},
        },
    )

    llms = main_module.get_config_llms()

    assert {llm.name for llm in llms} == {"llm_a", "llm_b"}


@pytest.mark.asyncio
async def test_datasources_config(monkeypatch):
    def fake_load():
        return {"datasources": {"Source": {"data_subdir": "src"}}}

    monkeypatch.setattr("pipeline.db.load_datasources_config", fake_load)
    result = await main_module.get_datasources_config()
    assert "Source" in result


@pytest.mark.asyncio
async def test_generate_summary(monkeypatch):
    async def fake_generate(
        query: str,
        results: list,
        max_results: int,
        model_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        return "summary"

    def fake_render(query: str, results: list, max_results: int):
        return "prompt"

    llm_module = ModuleType("llm_service")
    llm_module.generate_ai_summary = fake_generate
    llm_module.render_prompt = fake_render
    monkeypatch.setitem(sys.modules, "llm_service", llm_module)

    request = _make_request(method="POST", path="/ai-summary")
    body = main_module.AISummaryRequest(query="q", results=[_make_search_result()])
    response = await main_module.generate_summary(request, body)

    assert response.summary == "summary"
    assert response.prompt == "prompt"
    assert response.results_count == 1


@pytest.mark.asyncio
async def test_stream_summary(monkeypatch):
    async def fake_stream(
        query: str,
        results: list,
        max_results: int,
        model_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        for token in ["a", "b"]:
            yield token

    def fake_render(query: str, results: list, max_results: int):
        return "prompt"

    llm_module = ModuleType("llm_service")
    llm_module.stream_ai_summary = fake_stream
    llm_module.render_prompt = fake_render
    monkeypatch.setitem(sys.modules, "llm_service", llm_module)

    request = _make_request(method="POST", path="/ai-summary/stream")
    body = main_module.AISummaryRequest(query="q", results=[_make_search_result()])
    response = await main_module.stream_summary(request, body)

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)

    joined = "".join(chunks)
    assert '"type": "prompt"' in joined
    assert '"type": "token"' in joined
    assert '"type": "done"' in joined


def test_health():
    assert main_module.health() == {"status": "healthy"}


def _make_db_mock() -> Any:
    db = SimpleNamespace()
    db.documents_collection = "documents"
    db.chunks_collection = "chunks"
    db.data_source = "uneg"
    db.client = SimpleNamespace()
    return db


def test_get_stats(monkeypatch):
    class PgMock:
        def fetch_status_counts(self):
            return {"indexed": 2, "parsed": 1}

        def fetch_field_status_breakdown(self, field, from_sys_data=False):
            if field == "map_organization":
                return {"Org": {"indexed": 2}}
            return {}

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    result = main_module.get_stats()
    assert result["total_documents"] == 3
    assert result["indexed_documents"] == 2


def test_get_stats_uses_pg(monkeypatch):
    class PgMock:
        def fetch_status_counts(self):
            return {"indexed": 2, "parsed": 1}

        def fetch_field_status_breakdown(self, field, from_sys_data=False):
            if field == "map_organization":
                return {"Org": {"indexed": 2}}
            return {}

    monkeypatch.setattr(
        main_module,
        "get_db_for_source",
        lambda _: (_ for _ in ()).throw(RuntimeError()),
    )
    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    result = main_module.get_stats()
    assert result["total_documents"] == 3
    assert result["indexed_documents"] == 2


@pytest.mark.asyncio
async def test_get_documents(monkeypatch):
    class PgMock:
        def get_paginated_documents(self, **kwargs):
            return {
                "documents": [{"title": "Doc"}],
                "total": 1,
            }

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    result = await main_module.get_documents(
        organization=None,
        document_type=None,
        published_year=None,
        language=None,
        file_format=None,
        status=None,
        title=None,
        search=None,
        page=1,
        page_size=20,
        data_source=None,
        target_language=None,
        toc_approved=None,
        sdg=None,
        sort_by="year",
        order="desc",
    )
    assert result["total"] == 1
    assert result["documents"][0]["title"] == "Doc"


@pytest.mark.asyncio
async def test_get_documents_translation(monkeypatch):
    class PgMock:
        def get_paginated_documents(self, **kwargs):
            return {
                "documents": [
                    {"title": "Doc", "full_summary": "Summary", "language": "en"}
                ],
                "total": 1,
            }

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    async def fake_translate(
        text: str, target_language: str, source_language: str | None = None
    ) -> str:
        return f"{text}-{target_language}"

    llm_module = ModuleType("ui.backend.services.llm_service")
    llm_module.translate_text = fake_translate
    monkeypatch.setitem(sys.modules, "ui.backend.services.llm_service", llm_module)

    result = await main_module.get_documents(
        organization=None,
        document_type=None,
        published_year=None,
        language=None,
        file_format=None,
        status=None,
        title=None,
        search=None,
        page=1,
        page_size=20,
        data_source=None,
        target_language="fr",
        toc_approved=None,
        sdg=None,
        sort_by="year",
        order="desc",
    )
    assert result["documents"][0]["title"].endswith("-fr")


@pytest.mark.asyncio
async def test_title_search(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    hit = SimpleNamespace(
        payload={
            "doc_id": "doc-1",
            "map_title": "Title",
            "map_organization": "Org",
            "map_published_year": "2024",
        },
        score=0.9,
    )
    monkeypatch.setattr(main_module, "search_titles", lambda **kwargs: [hit])

    results = await main_module.perform_title_search(
        _make_request(path="/search/titles"),
        q="query",
    )
    assert results[0]["doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_search_endpoint(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)
    pg = SimpleNamespace()
    pg.fetch_docs = lambda doc_ids: {
        "doc-1": {"map_title": "Doc", "map_organization": "Org"}
    }
    pg.fetch_chunks = lambda chunk_ids: {
        "chunk-1": {"sys_page_num": 1, "sys_bbox": [], "sys_headings": ["H1"]}
    }
    pg.fetch_indexed_doc_ids = lambda: ["doc-1", "doc-2", "doc-3"]
    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: pg)

    hit = SimpleNamespace(
        id="chunk-1",
        score=0.8,
        payload={
            "doc_id": "doc-1",
            "sys_text": "Chunk text",
        },
    )

    def fake_search_chunks(*_args, **_kwargs):
        return [hit]

    monkeypatch.setattr(main_module, "search_chunks", fake_search_chunks)

    result = await main_module.search(
        _make_request(path="/search"),
        q="health",
        limit=10,
        organization=None,
        title=None,
        published_year=None,
        document_type=None,
        country=None,
        language=None,
        dense_weight=None,
        rerank=False,
        recency_boost=False,
        recency_weight=0.15,
        recency_scale_days=365,
        section_types=None,
        keyword_boost_short_queries=True,
        data_source=None,
        min_chunk_size=0,
        model=None,
        rerank_model=None,
        rerank_model_page_size=None,
        auto_min_score=False,
        deduplicate=True,
        field_boost=True,
        field_boost_fields=None,
    )
    assert result.total == 1
    assert result.results[0].doc_id == "doc-1"


@pytest.mark.asyncio
async def test_search_facet_values(monkeypatch):
    monkeypatch.setattr(
        main_module, "search_facet_values", lambda **kwargs: ["Org1", "Org2"]
    )
    result = await main_module.search_facet_values_endpoint(
        _make_request(path="/search/facet-values"), field="organization", q="org"
    )
    assert result == ["Org1", "Org2"]


@pytest.mark.asyncio
async def test_get_facets(monkeypatch):
    db = _make_db_mock()
    db.get_all_documents_projection = lambda fields: [
        {
            "map_organization": "OrgA",
            "map_published_year": "2020",
            "map_document_type": "Eval",
        },
        {
            "map_organization": "OrgA",
            "map_published_year": "2020",
            "map_document_type": "Eval",
        },
        {
            "map_organization": "OrgB",
            "map_published_year": "2021",
            "map_document_type": "Eval",
        },
    ]

    def facet_documents(key, filter_conditions=None, limit=2000, exact=False):
        counts = Counter()
        for row in db.get_all_documents_projection([key]):
            value = row.get(key)
            if value is None:
                continue
            counts[value] += 1
        return dict(counts)

    db.facet_documents = facet_documents
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)
    monkeypatch.setattr(
        main_module,
        "get_filter_fields",
        lambda *_: {"organization": "Organization", "published_year": "Year"},
    )
    result = await main_module.get_facets(
        _make_request(path="/facets"),
        organization=None,
        title=None,
        published_year=None,
        document_type=None,
        country=None,
        language=None,
        data_source=None,
        q=None,
    )
    assert result.facets["organization"][0].value == "OrgA"


@pytest.mark.asyncio
async def test_get_document(monkeypatch):
    db = _make_db_mock()
    db.get_document = lambda doc_id: {"id": doc_id, "title": "Na\ufffdonal"}
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    doc = await main_module.get_document("doc-1")
    assert doc["title"] == "National"


@pytest.mark.asyncio
async def test_get_document_prefers_pg(monkeypatch):
    class PgMock:
        def fetch_docs(self, doc_ids):
            return {str(doc_ids[0]): {"id": doc_ids[0], "map_title": "Title"}}

    monkeypatch.setattr(
        main_module,
        "get_db_for_source",
        lambda _: (_ for _ in ()).throw(RuntimeError()),
    )
    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    doc = await main_module.get_document("doc-1")
    assert doc["title"] == "Title"


@pytest.mark.asyncio
async def test_get_document_logs_missing_folder(monkeypatch):
    db = _make_db_mock()
    db.get_document = lambda doc_id: {"id": doc_id, "sys_parsed_folder": None}
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    result = await main_module.get_document_logs("doc-1")
    assert "No parsed folder" in result["error"]


@pytest.mark.asyncio
async def test_update_document_toc(monkeypatch):
    db = _make_db_mock()
    doc = {"id": "doc-1", "sys_toc_classified": "old"}
    db.get_document = lambda doc_id: doc
    db.update_document = lambda doc_id, payload: doc.update(payload)
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    result = await main_module.update_document_toc(
        "doc-1", main_module.TocUpdate(toc_classified="new")
    )
    assert result["success"] is True
    assert doc["sys_toc_classified"] == "new"
    assert doc["sys_user_edited_section_types"] is True


@pytest.mark.asyncio
async def test_update_document_metadata(monkeypatch):
    db = _make_db_mock()
    doc = {"id": "doc-1", "sys_toc_approved": False}
    db.get_document = lambda doc_id: doc
    db.update_document = lambda doc_id, payload: doc.update(payload)
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    result = await main_module.update_document_metadata(
        "doc-1", main_module.DocumentMetadataUpdate(toc_approved=True)
    )
    assert result["doc"]["toc_approved"] is True


@pytest.mark.asyncio
async def test_update_document_metadata_uses_pg_when_no_update(monkeypatch):
    doc = {"id": "doc-1", "sys_toc_approved": False}
    db = _make_db_mock()
    db.get_document = lambda doc_id: doc
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    calls = {}

    class PgMock:
        def merge_doc_sys_fields(self, *, doc_id, sys_fields):
            calls["doc_id"] = doc_id
            calls["sys_fields"] = sys_fields

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    result = await main_module.update_document_metadata(
        "doc-1", main_module.DocumentMetadataUpdate(toc_approved=True)
    )
    assert result["doc"]["toc_approved"] is True
    assert calls["sys_fields"]["sys_toc_approved"] is True


@pytest.mark.asyncio
async def test_get_document_chunks(monkeypatch):
    db = _make_db_mock()
    db.client.scroll = lambda **kwargs: (
        [
            SimpleNamespace(
                id="chunk-1",
                payload={
                    "doc_id": "doc-1",
                    "sys_text": "Chunk text",
                    "sys_page_num": 1,
                    "sys_headings": [],
                    "sys_bbox": [],
                },
            )
        ],
        None,
    )
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    class PgMock:
        def fetch_chunks(self, chunk_ids):
            return {
                str(cid): {
                    "sys_page_num": 1,
                    "sys_headings": [],
                    "sys_bbox": [],
                }
                for cid in chunk_ids
            }

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())

    result = await main_module.get_document_chunks(
        "doc-1",
        data_source=None,
        target_language=None,
    )
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_reprocess_document_toc_enqueues(monkeypatch):
    task = SimpleNamespace(id="task-1")
    task_module = ModuleType("pipeline.utilities.tasks")
    task_module.reprocess_document_toc = SimpleNamespace(delay=lambda **_: task)
    monkeypatch.setitem(sys.modules, "pipeline.utilities.tasks", task_module)

    result = await main_module.reprocess_document_toc("doc-1")
    assert result["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_queue_status(monkeypatch):
    inspector = SimpleNamespace(
        active=lambda: {"worker": [{"id": "task-1"}]},
        reserved=lambda: {},
        scheduled=lambda: {},
    )

    class FakeResult:
        def __init__(self):
            self.info = {"log": "running"}
            self.state = "PROGRESS"

    monkeypatch.setattr(main_module.celery_app.control, "inspect", lambda: inspector)
    monkeypatch.setattr(main_module.celery_app, "AsyncResult", lambda _: FakeResult())

    result = await main_module.get_queue_status()
    assert result["active"]["worker"][0]["output"] == "running"


@pytest.mark.asyncio
async def test_reprocess_document_enqueues(monkeypatch):
    db = _make_db_mock()
    db.get_document = lambda doc_id: {"id": doc_id, "filepath": "/tmp/doc.pdf"}
    db.delete_document_chunks = lambda doc_id: None
    db.update_document = lambda doc_id, payload: None
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    task = SimpleNamespace(id="task-1")
    task_module = ModuleType("pipeline.utilities.tasks")
    task_module.reprocess_document = SimpleNamespace(delay=lambda *args: task)
    monkeypatch.setitem(sys.modules, "pipeline.utilities.tasks", task_module)

    result = await main_module.reprocess_document("doc-1")
    assert result["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_serve_pdf(monkeypatch, tmp_path):
    db = _make_db_mock()
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    db.get_document = lambda doc_id: {"filepath": str(pdf_path)}
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    response = await main_module.serve_pdf("doc-1")
    assert response.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_serve_file(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    # Files must be under data/ directory per security constraints
    base = tmp_path / "data" / "images"
    base.mkdir(parents=True, exist_ok=True)
    file_path = base / "image.png"
    file_path.write_bytes(b"data")

    response = await main_module.serve_file("data/images/image.png")
    assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_get_chunk_highlights(monkeypatch):
    db = _make_db_mock()
    db.client.retrieve = lambda **kwargs: [
        SimpleNamespace(
            payload={
                "sys_text": "Text",
                "sys_bbox": [(1, (1, 2, 3, 4))],
                "sys_page_num": 1,
            }
        )
    ]
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    response = await main_module.get_chunk_highlights("chunk-1")
    assert response.total == 1


@pytest.mark.asyncio
async def test_get_chunk_highlights_uses_pg(monkeypatch):
    class PgMock:
        def fetch_chunks(self, chunk_ids):
            return {
                str(chunk_ids[0]): {
                    "sys_text": "Text",
                    "sys_bbox": [(1, (1, 2, 3, 4))],
                    "sys_page_num": 1,
                }
            }

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: _make_db_mock())

    response = await main_module.get_chunk_highlights("chunk-1")
    assert response.total == 1


@pytest.mark.asyncio
async def test_get_highlights(monkeypatch):
    db = _make_db_mock()
    db.client.scroll = lambda **kwargs: (
        [
            SimpleNamespace(
                payload={
                    "sys_text": "Hello",
                    "sys_page_num": 2,
                    "sys_bbox": [(1, 2, 3, 4)],
                }
            )
        ],
        None,
    )
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: db)

    response = await main_module.get_highlights(
        "doc-1",
        page=2,
        text=None,
        data_source=None,
    )
    assert response.total == 1


@pytest.mark.asyncio
async def test_get_highlights_uses_pg(monkeypatch):
    class PgMock:
        def fetch_chunks_for_doc(self, doc_id):
            return [
                {
                    "sys_text": "Hello",
                    "sys_page_num": 2,
                    "sys_bbox": [(1, 2, 3, 4)],
                }
            ]

    monkeypatch.setattr(main_module, "get_pg_for_source", lambda _: PgMock())
    monkeypatch.setattr(main_module, "get_db_for_source", lambda _: _make_db_mock())

    response = await main_module.get_highlights(
        "doc-1",
        page=2,
        text=None,
        data_source=None,
    )
    assert response.total == 1


@pytest.mark.asyncio
async def test_highlight_endpoint_keyword_only():
    request = main_module.UnifiedHighlightRequest(
        query="hello", text="hello world", highlight_type="keyword"
    )
    response = await main_module.highlight_text(request)
    assert response.total == 1


def test_infer_paragraphs_from_bboxes_no_change():
    text = "Sentence one. Sentence two."
    assert main_module.infer_paragraphs_from_bboxes(text, []) == text
    assert main_module.infer_paragraphs_from_bboxes(text, [(0, 0, 10, 10)]) == text


def test_infer_paragraphs_from_bboxes_inserts_breaks():
    text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
    bboxes = [
        (0, 0, 10, 10),
        (0, 12, 10, 22),
        (0, 24, 10, 34),
        (0, 36, 10, 46),
        (0, 100, 10, 110),
        (0, 112, 10, 122),
    ]
    result = main_module.infer_paragraphs_from_bboxes(text, bboxes)
    assert result == text


def test_find_semantic_matches_sync_finds_phrase():
    original = "Hello world"
    clean = original.lower()
    index_map = list(range(len(original))) + [len(original)]
    matches = main_module.find_semantic_matches_sync(
        phrases=["hello world"],
        clean_text=clean,
        original_text=original,
        index_map=index_map,
    )
    assert len(matches) == 1
    assert matches[0].text == "Hello world"


# ---------- _build_facets_from_pg / sys_* routing tests ----------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakePg:
    def __init__(self, rows):
        self.docs_table = "docs_uneg"
        self._rows = rows

    def _get_conn(self):
        return _FakeConn(self._rows)


def test_build_facets_from_pg_returns_counts():
    pg = _FakePg([("en", 100), ("fr", 20), ("es", 10)])
    result = facet_module.build_facets_from_pg(pg, "sys_language")
    assert result == {"en": 100, "fr": 20, "es": 10}


def test_build_facets_from_pg_empty():
    pg = _FakePg([])
    result = facet_module.build_facets_from_pg(pg, "sys_language")
    assert result == {}


def _fake_resolve_storage_field(core_field, data_source):
    return "sys_language" if core_field == "language" else f"map_{core_field}"


def test_build_facets_from_db_routes_sys_fields_to_pg():
    """sys_* storage fields should be fetched from PostgreSQL, not Qdrant."""
    db = _make_db_mock()
    qdrant_called_with = []

    def facet_documents(key, filter_conditions=None, limit=2000, exact=False):
        qdrant_called_with.append(key)
        return {"OrgA": 5}

    db.facet_documents = facet_documents

    pg = _FakePg([("en", 100), ("fr", 20)])

    filter_fields = {"organization": "Organization", "language": "Language"}
    result = facet_module.build_facets_from_db(
        db, filter_fields, None, _fake_resolve_storage_field, pg=pg
    )

    # Organization should go through Qdrant
    assert "map_organization" in qdrant_called_with
    # Language should NOT go through Qdrant (sys_* -> PG)
    assert "sys_language" not in qdrant_called_with

    # Language facets should come from PG with full names
    lang_values = {fv.value: fv.count for fv in result["language"]}
    assert lang_values == {"English": 100, "French": 20}

    # Organization facets should come from Qdrant
    assert result["organization"][0].value == "OrgA"


def test_build_facets_from_db_falls_back_to_qdrant_without_pg():
    """When pg is None, sys_* fields fall back to Qdrant query."""
    db = _make_db_mock()
    qdrant_called_with = []

    def facet_documents(key, filter_conditions=None, limit=2000, exact=False):
        qdrant_called_with.append(key)
        return {}

    db.facet_documents = facet_documents

    filter_fields = {"language": "Language"}
    result = facet_module.build_facets_from_db(
        db, filter_fields, None, _fake_resolve_storage_field, pg=None
    )

    # Without pg, sys_language should still go through Qdrant
    assert "sys_language" in qdrant_called_with
    assert result["language"] == []


def test_language_codes_roundtrip():
    """Every code maps to a name and every name maps back to its code."""
    for code, name in LANGUAGE_NAMES.items():
        assert LANGUAGE_CODES[name] == code


def test_normalize_language_filter_maps_names_to_codes():
    assert search_module._normalize_language_filter("English") == "en"
    assert search_module._normalize_language_filter("French,Spanish") == "fr,es"


def test_normalize_language_filter_passes_through_codes():
    """Unknown values (including raw codes) pass through unchanged."""
    assert search_module._normalize_language_filter("en") == "en"
    assert search_module._normalize_language_filter("Unknown") == "Unknown"


def test_normalize_language_filter_none():
    assert search_module._normalize_language_filter(None) is None
    assert search_module._normalize_language_filter("") is None


def test_language_facets_map_codes_to_full_names():
    """Language facets should display full names, not two-letter codes."""
    db = _make_db_mock()
    db.facet_documents = lambda **kw: {}

    pg = _FakePg([("en", 50), ("fr", 10), ("Unknown", 3)])

    filter_fields = {"language": "Language"}
    result = facet_module.build_facets_from_db(
        db, filter_fields, None, _fake_resolve_storage_field, pg=pg
    )

    lang_values = {fv.value: fv.count for fv in result["language"]}
    assert lang_values["English"] == 50
    assert lang_values["French"] == 10
    # Unknown codes pass through unchanged
    assert lang_values["Unknown"] == 3
