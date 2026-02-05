import sys
from types import ModuleType, SimpleNamespace

import pytest

import ui.backend.services.search as search
import ui.backend.services.search_models as search_models


class _FakeArray:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


class _FakeDenseModel:
    def __init__(self, vector):
        self._vector = vector

    def embed(self, _items):
        return [self._vector]


class _FakeSparseModel:
    def __init__(self, indices, values):
        self._indices = indices
        self._values = values

    def embed(self, _items):
        return [SimpleNamespace(indices=self._indices, values=self._values)]


def _make_fake_db(query_points_result=None, facet_result=None, scroll_result=None):
    calls = []

    class _Client:
        def query_points(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(points=query_points_result or [])

        def scroll(self, **kwargs):
            calls.append(kwargs)
            return (scroll_result or [], None)

        def facet(self, **kwargs):
            calls.append(kwargs)
            return facet_result

    return SimpleNamespace(
        documents_collection="documents",
        chunks_collection="chunks",
        client=_Client(),
        _calls=calls,
        data_source="uneg",
    )


def test_get_dense_model_invalid_vector_name(monkeypatch):
    monkeypatch.setattr(
        search,
        "DB_VECTORS",
        {"default": {"model_id": "m1", "enabled": True}},
        raising=False,
    )
    monkeypatch.setattr(search, "DENSE_VECTOR_NAME", "default", raising=False)
    monkeypatch.setattr(search, "_dense_models_cache", {}, raising=False)

    with pytest.raises(ValueError):
        search.get_dense_model("missing")


def test_get_dense_model_azure_requires_env(monkeypatch):
    monkeypatch.setattr(
        search,
        "DB_VECTORS",
        {"azure": {"model_id": "deploy", "source": "azure_foundry", "enabled": True}},
        raising=False,
    )
    monkeypatch.setattr(search, "DENSE_VECTOR_NAME", "azure", raising=False)
    monkeypatch.setattr(search, "_dense_models_cache", {}, raising=False)
    monkeypatch.delenv("AZURE_FOUNDRY_KEY", raising=False)
    monkeypatch.delenv("AZURE_FOUNDRY_ENDPOINT", raising=False)

    with pytest.raises(ValueError):
        search.get_dense_model("azure")


def test_get_dense_model_caches_local(monkeypatch):
    calls = []
    fastembed_module = ModuleType("fastembed")

    class FakeEmbedding:
        def __init__(self, model_name):
            calls.append(model_name)

    fastembed_module.TextEmbedding = FakeEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)

    monkeypatch.setattr(
        search,
        "DB_VECTORS",
        {"local": {"model_id": "model-1", "source": "huggingface", "enabled": True}},
        raising=False,
    )
    monkeypatch.setattr(search, "DENSE_VECTOR_NAME", "local", raising=False)
    monkeypatch.setattr(search, "_dense_models_cache", {}, raising=False)
    monkeypatch.setattr(search_models, "USE_EMBEDDING_SERVER", False, raising=False)

    model_first = search.get_dense_model("local")
    model_second = search.get_dense_model("local")

    assert model_first is model_second
    assert calls == ["model-1"]


def test_get_sparse_model_caches(monkeypatch):
    calls = []
    fastembed_module = ModuleType("fastembed")

    class FakeSparseEmbedding:
        def __init__(self, model_name):
            calls.append(model_name)

    fastembed_module.SparseTextEmbedding = FakeSparseEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)
    monkeypatch.setattr(search, "_sparse_model", None, raising=False)

    first = search.get_sparse_model()
    second = search.get_sparse_model()

    assert first is second
    assert calls == [search.SPARSE_MODEL]


def test_get_rerank_model_caches(monkeypatch):
    calls = []
    fastembed_module = ModuleType("fastembed")
    rerank_module = ModuleType("fastembed.rerank")
    cross_encoder_module = ModuleType("fastembed.rerank.cross_encoder")

    class FakeCrossEncoder:
        def __init__(self, model_name):
            calls.append(model_name)

    cross_encoder_module.TextCrossEncoder = FakeCrossEncoder

    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)
    monkeypatch.setitem(sys.modules, "fastembed.rerank", rerank_module)
    monkeypatch.setitem(
        sys.modules, "fastembed.rerank.cross_encoder", cross_encoder_module
    )
    monkeypatch.setattr(search, "_rerank_models_cache", {}, raising=False)
    monkeypatch.setattr(search, "SUPPORTED_RERANK_MODELS", {}, raising=False)

    first = search.get_rerank_model()
    second = search.get_rerank_model()

    assert first is second
    assert calls == [search.RERANK_MODEL]


def test_rerank_results_updates_scores_and_limit(monkeypatch):
    rerank_scores = [0.2, 0.9]

    class FakeReranker:
        def rerank(self, _query, _documents):
            return rerank_scores

    results = [
        SimpleNamespace(payload={"text": "one"}, score=0.1),
        SimpleNamespace(payload={"text": "two"}, score=0.2),
        SimpleNamespace(payload={"text": "three"}, score=0.3),
    ]

    monkeypatch.setattr(search, "get_rerank_model", lambda _model=None: FakeReranker())

    reranked = search.rerank_results("query", results, limit=2, max_rerank_candidates=2)

    assert [result.score for result in reranked] == [0.9, 0.2]
    assert reranked[0].payload["text"] == "two"


def test_get_models_returns_both(monkeypatch):
    dense_model = object()
    sparse_model = object()
    monkeypatch.setattr(search, "get_dense_model", lambda _name=None: dense_model)
    monkeypatch.setattr(search, "get_sparse_model", lambda: sparse_model)

    dense, sparse = search.get_models()
    assert dense is dense_model
    assert sparse is sparse_model


def test_search_titles_keyword_query():
    fake_db = _make_fake_db(
        scroll_result=[
            SimpleNamespace(id="doc1", payload={"map_title": "Main Report Liberia"}),
            SimpleNamespace(id="doc2", payload={"map_title": "Liberia Evaluation"}),
            SimpleNamespace(id="doc3", payload={"map_title": "Other Document"}),
        ]
    )

    results = search.search_titles("main liberia", db=fake_db)

    assert len(results) == 2
    assert results[0].payload["map_title"] == "Main Report Liberia"
    assert fake_db._calls[0]["collection_name"] == "documents"
    assert "scroll_filter" in fake_db._calls[0]


def test_search_facet_values_filters_and_maps(monkeypatch):
    class Hit:
        def __init__(self, value, count):
            self.value = value
            self.count = count

    fake_db = _make_fake_db(
        facet_result=SimpleNamespace(hits=[Hit("Org A", 3), Hit("Other", 1)])
    )

    results = search.search_facet_values(
        field="organization",
        query="org",
        db=fake_db,
        data_source="uneg",
        limit=10,
    )

    assert results == [{"value": "Org A", "count": 3}]


def test_search_facet_values_returns_empty_on_error(monkeypatch):
    class _Client:
        def facet(self, **_kwargs):
            raise RuntimeError("boom")

    fake_db = SimpleNamespace(documents_collection="documents", client=_Client())
    assert (
        search.search_facet_values(
            field="organization",
            query="org",
            db=fake_db,
            data_source="uneg",
            limit=10,
        )
        == []
    )
