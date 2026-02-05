"""
Unit tests for short query keyword boost functionality in search.
Tests the actual backend search logic and scoring behavior.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from ui.backend.services.search import search_chunks


def _make_point(point_id: str, score: float):
    return SimpleNamespace(id=point_id, score=score, payload={"text": "sample text"})


def _setup_mock_models():
    """Helper to set up mock embedding models with proper return types."""
    mock_dense_model = MagicMock()
    mock_sparse_model = MagicMock()

    mock_dense_model.embed.return_value = [np.array([0.1] * 4)]

    mock_sparse_vec = SimpleNamespace(
        indices=np.array([1, 2, 3]), values=np.array([0.5, 0.3, 0.2])
    )
    mock_sparse_model.embed.return_value = [mock_sparse_vec]

    return mock_dense_model, mock_sparse_model


def _setup_mock_db(dense_points, sparse_points):
    mock_db = MagicMock()
    mock_db.chunks_collection = "chunks"
    mock_db.client.query_points.side_effect = [
        SimpleNamespace(points=dense_points),
        SimpleNamespace(points=sparse_points),
    ]
    return mock_db


class TestShortQueryKeywordBoost:
    """Test the short query keyword boost logic in search_chunks()."""

    @patch("ui.backend.services.search.get_dense_model")
    @patch("ui.backend.services.search.get_sparse_model")
    @patch.dict(os.environ, {"SHORT_QUERY_DENSE_WEIGHT": "0.25"})
    def test_short_query_boost_changes_rrf_order(
        self, mock_sparse_model, mock_dense_model
    ):
        mock_dense, mock_sparse = _setup_mock_models()
        mock_dense_model.return_value = mock_dense
        mock_sparse_model.return_value = mock_sparse

        dense_points = [_make_point("A", 0.9), _make_point("B", 0.8)]
        sparse_points = [_make_point("B", 0.95), _make_point("A", 0.85)]

        mock_db = _setup_mock_db(dense_points, sparse_points)

        results = search_chunks(
            query="health",
            limit=2,
            dense_weight=0.8,
            db=mock_db,
            keyword_boost_short_queries=True,
        )

        assert [r.id for r in results] == ["B", "A"]

    @patch("ui.backend.services.search.get_dense_model")
    @patch("ui.backend.services.search.get_sparse_model")
    def test_long_query_keeps_dense_weight(self, mock_sparse_model, mock_dense_model):
        mock_dense, mock_sparse = _setup_mock_models()
        mock_dense_model.return_value = mock_dense
        mock_sparse_model.return_value = mock_sparse

        dense_points = [_make_point("A", 0.9), _make_point("B", 0.8)]
        sparse_points = [_make_point("B", 0.95), _make_point("A", 0.85)]

        mock_db = _setup_mock_db(dense_points, sparse_points)

        results = search_chunks(
            query="coral reef health",
            limit=2,
            dense_weight=0.8,
            db=mock_db,
            keyword_boost_short_queries=True,
        )

        assert [r.id for r in results] == ["A", "B"]

    @patch("ui.backend.services.search.get_dense_model")
    @patch("ui.backend.services.search.get_sparse_model")
    def test_boost_disabled_uses_provided_weight(
        self, mock_sparse_model, mock_dense_model
    ):
        mock_dense, mock_sparse = _setup_mock_models()
        mock_dense_model.return_value = mock_dense
        mock_sparse_model.return_value = mock_sparse

        dense_points = [_make_point("A", 0.9), _make_point("B", 0.8)]
        sparse_points = [_make_point("B", 0.95), _make_point("A", 0.85)]

        mock_db = _setup_mock_db(dense_points, sparse_points)

        results = search_chunks(
            query="health",
            limit=2,
            dense_weight=0.8,
            db=mock_db,
            keyword_boost_short_queries=False,
        )

        assert [r.id for r in results] == ["A", "B"]
