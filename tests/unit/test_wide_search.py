"""Wide search: Qdrant grouped queries spread results across documents."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from qdrant_client.http import models

from ui.backend.services.search import (
    SPARSE_VECTOR_NAME,
    _resolve_dense_model_name,
    search_chunks,
)
from ui.backend.services.search_wide import WIDE_GROUP_BY_FIELD, _merge_grouped_hybrid

pytestmark = pytest.mark.unit


def _hit(chunk_id, doc_id, score):
    return SimpleNamespace(id=chunk_id, score=score, payload={"doc_id": doc_id})


def _group(doc_id, hits):
    return SimpleNamespace(id=doc_id, hits=hits)


def _make_dense_model():
    model = MagicMock()
    model.embed.return_value = [np.array([0.2, 0.1, 0.4])]
    return model


def _make_sparse_model():
    model = MagicMock()
    model.embed.return_value = [
        SimpleNamespace(indices=np.array([1, 4]), values=np.array([0.5, 0.3]))
    ]
    return model


def _make_db(groups_by_using):
    """Fake db whose grouped query answers per vector name."""
    db = MagicMock()
    db.chunks_collection = "chunks_test"

    def query_points_groups(**kwargs):
        return SimpleNamespace(groups=groups_by_using[kwargs["using"]])

    db.client.query_points_groups.side_effect = query_points_groups
    return db


def _run(db, **kwargs):
    with patch(
        "ui.backend.services.search.get_dense_model", return_value=_make_dense_model()
    ), patch(
        "ui.backend.services.search.get_sparse_model", return_value=_make_sparse_model()
    ):
        return search_chunks(
            query="school feeding programmes",
            db=db,
            keyword_boost_short_queries=False,
            wide_search=True,
            **kwargs,
        )


def test_wide_search_dense_only_uses_one_grouped_query_and_keeps_group_order():
    dense_model = _resolve_dense_model_name(None)
    groups = [
        _group("doc-a", [_hit("a1", "doc-a", 0.9), _hit("a2", "doc-a", 0.8)]),
        _group("doc-b", [_hit("b1", "doc-b", 0.7)]),
    ]
    db = _make_db({dense_model: groups})

    results = _run(
        db, dense_weight=1.0, dense_model=dense_model, wide_limit=7, wide_group_size=2
    )

    db.client.query_points_groups.assert_called_once()
    kwargs = db.client.query_points_groups.call_args.kwargs
    assert kwargs["group_by"] == WIDE_GROUP_BY_FIELD
    assert kwargs["using"] == dense_model
    assert kwargs["limit"] == 7
    assert kwargs["group_size"] == 2
    assert "search_params" in kwargs
    db.client.query_points.assert_not_called()
    assert [r.id for r in results] == ["a1", "a2", "b1"]
    assert [r.score for r in results] == [0.9, 0.8, 0.7]


def test_wide_search_keyword_only_uses_sparse_grouped_query():
    groups = [_group("doc-k", [_hit("k1", "doc-k", 3.2)])]
    db = _make_db({SPARSE_VECTOR_NAME: groups})

    results = _run(db, dense_weight=0.0, wide_limit=3, wide_group_size=1)

    kwargs = db.client.query_points_groups.call_args.kwargs
    assert kwargs["using"] == SPARSE_VECTOR_NAME
    assert isinstance(kwargs["query"], models.SparseVector)
    assert "search_params" not in kwargs
    assert [r.id for r in results] == ["k1"]


def test_wide_search_hybrid_runs_both_grouped_queries_with_double_document_limit():
    dense_model = _resolve_dense_model_name(None)
    db = _make_db(
        {
            dense_model: [_group("doc-a", [_hit("a1", "doc-a", 0.9)])],
            SPARSE_VECTOR_NAME: [_group("doc-b", [_hit("b1", "doc-b", 2.0)])],
        }
    )

    results = _run(
        db, dense_weight=0.8, dense_model=dense_model, wide_limit=10, wide_group_size=5
    )

    calls = db.client.query_points_groups.call_args_list
    assert [c.kwargs["using"] for c in calls] == [dense_model, SPARSE_VECTOR_NAME]
    assert all(c.kwargs["limit"] == 20 for c in calls)
    assert all(c.kwargs["group_size"] == 5 for c in calls)
    # Dense side weighted 0.8 outranks the sparse-only document.
    assert [r.id for r in results] == ["a1", "b1"]


def test_merge_grouped_hybrid_ranks_documents_by_weighted_rrf():
    dense = [_group("A", [_hit("a1", "A", 0.9)]), _group("B", [_hit("b1", "B", 0.8)])]
    sparse = [_group("B", [_hit("b2", "B", 5.0)]), _group("C", [_hit("c1", "C", 4.0)])]

    # B appears on both sides, so it leads either way; the weight decides
    # whether the dense-only A or the keyword-only C comes next.
    dense_heavy = _merge_grouped_hybrid(
        dense, sparse, weight=0.9, doc_limit=3, group_size=5
    )
    assert [h.payload["doc_id"] for h in dense_heavy] == ["B", "B", "A", "C"]

    keyword_heavy = _merge_grouped_hybrid(
        dense, sparse, weight=0.1, doc_limit=3, group_size=5
    )
    assert [h.payload["doc_id"] for h in keyword_heavy] == ["B", "B", "C", "A"]


def test_merge_grouped_hybrid_caps_chunks_per_document_and_dedupes_hits():
    shared = _hit("b1", "B", 0.8)
    dense = [_group("B", [shared, _hit("b2", "B", 0.7), _hit("b3", "B", 0.6)])]
    sparse = [_group("B", [_hit("b1", "B", 5.0), _hit("b4", "B", 4.0)])]

    merged = _merge_grouped_hybrid(dense, sparse, weight=0.5, doc_limit=5, group_size=3)

    assert [h.id for h in merged] == ["b1", "b2", "b3"]
    # every chunk carries its document's fused score
    assert len({h.score for h in merged}) == 1


def test_merge_grouped_hybrid_respects_document_limit():
    dense = [_group(d, [_hit(f"{d}1", d, 0.5)]) for d in ("A", "B", "C", "D")]
    merged = _merge_grouped_hybrid(dense, [], weight=1.0, doc_limit=2, group_size=5)
    assert [h.payload["doc_id"] for h in merged] == ["A", "B"]


def test_wide_search_effective_limit_is_documents_times_group_size():
    """`limit` no longer caps the result: wide_limit * wide_group_size does."""
    dense_model = _resolve_dense_model_name(None)
    groups = [
        _group(f"doc-{i}", [_hit(f"h{i}-{j}", f"doc-{i}", 0.5) for j in range(3)])
        for i in range(4)
    ]
    db = _make_db({dense_model: groups})

    results = _run(
        db,
        dense_weight=1.0,
        dense_model=dense_model,
        limit=2,
        wide_limit=4,
        wide_group_size=3,
    )

    assert len(results) == 12
