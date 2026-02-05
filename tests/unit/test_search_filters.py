import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from qdrant_client.http import models

from ui.backend.services.search import (
    SPARSE_VECTOR_NAME,
    apply_recency_boost,
    search_chunks,
)


def _make_dense_model():
    model = MagicMock()
    model.embed.return_value = [np.array([0.2, 0.1, 0.4])]
    return model


def _make_sparse_model():
    sparse_vec = SimpleNamespace(
        indices=np.array([1, 4, 7]),
        values=np.array([0.5, 0.3, 0.1]),
    )
    model = MagicMock()
    model.embed.return_value = [sparse_vec]
    return model


def _make_db(points):
    db = MagicMock()
    db.chunks_collection = "chunks_test"
    db.client.query_points.return_value = SimpleNamespace(points=points)
    return db


def test_search_chunks_uses_organization_filter():
    dense_model = _make_dense_model()
    sparse_model = _make_sparse_model()

    db = _make_db(points=[])
    with patch(
        "ui.backend.services.search.get_dense_model", return_value=dense_model
    ), patch("ui.backend.services.search.get_sparse_model", return_value=sparse_model):
        search_chunks(
            query="governance",
            dense_weight=1.0,
            filters={"organization": "UNDP"},
            db=db,
        )

    _, kwargs = db.client.query_points.call_args
    query_filter = kwargs.get("query_filter")
    assert query_filter is not None
    assert query_filter.must, "Expected filter conditions"
    condition = query_filter.must[0]
    assert condition.key == "map_organization"
    assert condition.match.value == "UNDP"


def test_search_chunks_keyword_only_uses_sparse_query():
    dense_model = _make_dense_model()
    sparse_model = _make_sparse_model()

    db = _make_db(points=[])
    with patch(
        "ui.backend.services.search.get_dense_model", return_value=dense_model
    ), patch("ui.backend.services.search.get_sparse_model", return_value=sparse_model):
        search_chunks(
            query="health",
            dense_weight=0.0,
            keyword_boost_short_queries=False,
            db=db,
        )

    _, kwargs = db.client.query_points.call_args
    assert kwargs["using"] == SPARSE_VECTOR_NAME
    assert isinstance(kwargs["query"], models.SparseVector)


def test_search_chunks_respects_min_chunk_size():
    dense_model = _make_dense_model()
    sparse_model = _make_sparse_model()

    short = SimpleNamespace(id="short", score=0.5, payload={"sys_text": "tiny"})
    long = SimpleNamespace(id="long", score=0.6, payload={"sys_text": "x" * 120})
    db = _make_db(points=[short, long])

    with patch(
        "ui.backend.services.search.get_dense_model", return_value=dense_model
    ), patch("ui.backend.services.search.get_sparse_model", return_value=sparse_model):
        results = search_chunks(
            query="evaluation",
            dense_weight=1.0,
            min_chunk_size=50,
            db=db,
        )

    assert [r.id for r in results] == ["long"]


def test_apply_recency_boost_prefers_recent_documents():
    now = datetime.datetime.now()
    recent_year = now.year
    older_year = now.year - 5

    recent = SimpleNamespace(
        id="recent",
        score=0.5,
        payload={
            "published_date_unix": int(datetime.datetime(recent_year, 1, 1).timestamp())
        },
    )
    older = SimpleNamespace(
        id="older",
        score=0.5,
        payload={
            "published_date_unix": int(datetime.datetime(older_year, 1, 1).timestamp())
        },
    )

    results = apply_recency_boost([older, recent], recency_weight=0.5, scale_days=365)

    assert results[0].id == "recent"
    assert (
        results[0].payload["_recency_factor"] >= results[1].payload["_recency_factor"]
    )
