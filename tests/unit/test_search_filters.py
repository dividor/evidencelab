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
from ui.backend.services.search_models import apply_field_boost


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


def test_apply_recency_boost_uses_map_published_year():
    """Recency boost should work with map_published_year when published_date_unix is absent."""
    now = datetime.datetime.now()

    recent = SimpleNamespace(
        id="recent",
        score=0.5,
        payload={"map_published_year": str(now.year)},
    )
    older = SimpleNamespace(
        id="older",
        score=0.5,
        payload={"map_published_year": str(now.year - 5)},
    )

    results = apply_recency_boost([older, recent], recency_weight=0.5, scale_days=365)

    assert results[0].id == "recent"
    assert results[0].payload["_recency_factor"] > results[1].payload["_recency_factor"]


# --- Field boost tests ---


def _make_search_result(id, score, organization=None, country=None, metadata=None):
    """Create a minimal SearchResult-like object for field boost tests."""
    from ui.backend.schemas import SearchResult

    md = metadata or {}
    if country:
        md["map_country"] = country
    return SearchResult(
        id=id,
        chunk_id=id,
        doc_id="doc1",
        text="sample text",
        page_num=1,
        headings=[],
        score=score,
        title="Test",
        organization=organization,
        metadata=md,
    )


def test_field_boost_country_match():
    """Results with matching country should be boosted above non-matching."""
    kenya = _make_search_result("a", 0.5, country="Kenya")
    uganda = _make_search_result("b", 0.5, country="Uganda")

    results = apply_field_boost(
        [uganda, kenya],
        query="girl education Kenya",
        boost_fields={"country": 0.5},
        known_values={"country": ["Kenya", "Uganda"]},
    )
    assert results[0].id == "a"
    assert results[0].score > results[1].score


def test_field_boost_organization_match():
    """Results with matching organization should be boosted."""
    undp = _make_search_result("a", 0.5, organization="UNDP")
    unicef = _make_search_result("b", 0.5, organization="UNICEF")

    results = apply_field_boost(
        [unicef, undp],
        query="governance UNDP report",
        boost_fields={"organization": 0.5},
        known_values={"organization": ["UNDP", "UNICEF"]},
    )
    assert results[0].id == "a"


def test_field_boost_multi_value_country():
    """Comma-separated country values should be split and each checked."""
    multi = _make_search_result("a", 0.5, country="Kenya, South Sudan")
    other = _make_search_result("b", 0.5, country="Uganda")

    results = apply_field_boost(
        [other, multi],
        query="education Kenya",
        boost_fields={"country": 0.5},
        known_values={"country": ["Kenya", "South Sudan", "Uganda"]},
    )
    assert results[0].id == "a"


def test_field_boost_case_insensitive():
    """Query matching should be case-insensitive."""
    kenya = _make_search_result("a", 0.5, country="Kenya")
    other = _make_search_result("b", 0.5, country="Uganda")

    results = apply_field_boost(
        [other, kenya],
        query="education kenya report",
        boost_fields={"country": 0.5},
        known_values={"country": ["Kenya", "Uganda"]},
    )
    assert results[0].id == "a"


def test_field_boost_multi_word_value():
    """Multi-word values like 'South Sudan' should match correctly."""
    south_sudan = _make_search_result("a", 0.5, country="South Sudan")
    sudan = _make_search_result("b", 0.5, country="Sudan")

    results = apply_field_boost(
        [sudan, south_sudan],
        query="education South Sudan",
        boost_fields={"country": 0.5},
        known_values={"country": ["South Sudan", "Sudan"]},
    )
    # "South Sudan" matched first (longest), so Sudan should NOT match
    assert results[0].id == "a"
    assert results[0].score > results[1].score


def test_field_boost_no_match_returns_unchanged_order():
    """When query doesn't mention any known values, order stays the same."""
    a = _make_search_result("a", 0.8, country="Kenya")
    b = _make_search_result("b", 0.6, country="Uganda")

    results = apply_field_boost(
        [a, b],
        query="education health assessment",
        boost_fields={"country": 0.5},
        known_values={"country": ["Kenya", "Uganda"]},
    )
    assert results[0].id == "a"
    assert results[1].id == "b"
    # Scores should be unchanged since no field values were detected in query
    assert results[0].score == 0.8
    assert results[1].score == 0.6


def test_field_boost_empty_config_returns_unchanged():
    """Empty boost_fields should return results unchanged."""
    a = _make_search_result("a", 0.5, country="Kenya")
    results = apply_field_boost(
        [a], query="education Kenya", boost_fields={}, known_values={}
    )
    assert results[0].score == 0.5


def test_field_boost_non_matching_score_unchanged():
    """Non-matching results must keep their original score (never penalized)."""
    kenya = _make_search_result("a", 0.5, country="Kenya")
    somalia = _make_search_result("b", 0.9, country="Somalia")

    results = apply_field_boost(
        [somalia, kenya],
        query="girl education Kenya",
        boost_fields={"country": 0.5},
        known_values={"country": ["Kenya", "Somalia"]},
    )
    # Somalia (0.9) still ahead of Kenya boosted (0.5 * 1.5 = 0.75)
    assert results[0].id == "b"
    # Somalia keeps its original score exactly (no penalty for non-match)
    assert results[0].score == 0.9
    # Kenya gets boosted
    assert results[1].id == "a"
    assert results[1].score == 0.5 * 1.5


def test_field_boost_combined_country_and_org():
    """Both country and org boost should compound."""
    match_both = _make_search_result("a", 0.4, organization="UNDP", country="Kenya")
    match_one = _make_search_result("b", 0.4, organization="UNICEF", country="Kenya")
    match_none = _make_search_result("c", 0.4, organization="UNICEF", country="Uganda")

    results = apply_field_boost(
        [match_none, match_one, match_both],
        query="governance UNDP Kenya",
        boost_fields={"country": 0.5, "organization": 0.5},
        known_values={
            "country": ["Kenya", "Uganda"],
            "organization": ["UNDP", "UNICEF"],
        },
    )
    assert results[0].id == "a"  # matches both: 0.4 * 2.0 = 0.8
    assert results[1].id == "b"  # matches country only: 0.4 * 1.5 = 0.6
    assert results[2].id == "c"  # matches neither: 0.4 (unchanged)
    assert results[2].score == 0.4  # never penalized
