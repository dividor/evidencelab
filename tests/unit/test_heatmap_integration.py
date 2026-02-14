"""
Unit tests for heatmap integration scenarios.

Tests cover both docs mode (/docsearch) and chunks mode (/search)
with regular filters and taxonomy filters.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import Request

from ui.backend.routes.search import docsearch, search


class FakeDB:
    """Fake database for testing."""

    def __init__(self, scroll_results=None, search_results=None):
        self.scroll_results = scroll_results or []
        self.search_results = search_results or []
        self.documents_collection = "documents_uneg"
        self.chunks_collection = "chunks_uneg"
        self.data_source = "uneg"
        self._scroll_calls = []
        self._search_calls = []

    def _search_conditions(self, query):
        """Mock search conditions."""
        from qdrant_client.http import models as qmodels

        return [
            qmodels.FieldCondition(
                key="map_title", match=qmodels.MatchText(text=query)
            ),
            qmodels.FieldCondition(
                key="sys_full_summary", match=qmodels.MatchText(text=query)
            ),
        ]

    def _scroll_documents(self, query_filter, end_idx):
        """Mock scroll documents."""
        self._scroll_calls.append({"filter": query_filter, "end_idx": end_idx})
        return self.scroll_results[:end_idx]

    def hybrid_search(self, **kwargs):
        """Mock hybrid search for chunks."""
        self._search_calls.append(kwargs)
        return self.search_results


def create_fake_document(doc_id, title, organization, year, summary="Test summary"):
    """Helper to create fake document points."""
    return SimpleNamespace(
        id=doc_id,
        payload={
            "map_title": title,
            "map_organization": organization,
            "map_published_year": year,
            "sys_full_summary": summary,
        },
    )


def create_fake_chunk(chunk_id, doc_id, text, score=0.8):
    """Helper to create fake chunk results."""
    return SimpleNamespace(
        id=chunk_id,
        score=score,
        payload={
            "doc_id": doc_id,
            "sys_doc_id": doc_id,
            "sys_text": text,
        },
    )


@pytest.fixture
def mock_pg():
    """Create a mock Postgres client."""
    mock = MagicMock()
    # By default, return all document IDs as indexed
    mock.fetch_indexed_doc_ids.return_value = ["1", "2", "3"]
    mock.fetch_docs.return_value = {}
    return mock


# ============================================================================
# DOCS MODE TESTS (no query, uses /docsearch endpoint)
# ============================================================================


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_organization_filter(mock_pg):
    """Test heatmap docs mode (no query) with organization filter."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Report A", "UNICEF", "2023"),
            create_fake_document("2", "Report B", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",  # No query = docs mode
                limit=50,
                organization="UNICEF",
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 2
    assert len(result.results) == 2
    assert all(r.organization == "UNICEF" for r in result.results)


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_year_filter(mock_pg):
    """Test heatmap docs mode with published_year filter."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Study 2023", "WHO", "2023"),
            create_fake_document("2", "Analysis 2023", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization=None,
                title=None,
                published_year="2023",
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 2
    assert len(result.results) == 2
    assert all(r.year == "2023" for r in result.results)


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_taxonomy_filter(mock_pg):
    """Test heatmap docs mode with taxonomy filter (tag_sdg)."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "SDG Education Report", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {"tag_sdg": "sdg4"}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    assert result.results[0].title == "SDG Education Report"
    # Verify taxonomy filter was included in the request
    assert len(fake_db._scroll_calls) == 1


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_mixed_filters(mock_pg):
    """Test heatmap docs mode with both regular and taxonomy filters."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Gender Report 2023", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {"tag_theme": "gender_equality"}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization="UNICEF",
                title=None,
                published_year="2023",
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    assert result.results[0].organization == "UNICEF"
    assert result.results[0].year == "2023"


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_country_filter(mock_pg):
    """Test heatmap docs mode with country filter."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Kenya Study", "WHO", "2023"),
            create_fake_document("2", "Kenya Analysis", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country="Kenya",
                language=None,
                data_source="uneg",
            )

    assert result.total == 2
    assert len(result.results) == 2


# ============================================================================
# CHUNKS MODE TESTS (with query, uses /search endpoint)
# ============================================================================


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_with_query_and_organization():
    """Test heatmap chunks mode (with query) with organization filter."""
    fake_db = FakeDB(search_results=[create_fake_chunk("chunk1", "doc1", "education")])

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {
        "doc1": {
            "map_title": "Education Report",
            "map_organization": "UNICEF",
            "map_published_year": "2023",
        }
    }
    mock_pg.fetch_chunks.return_value = {
        "chunk1": {"sys_text": "education", "sys_bbox": [], "sys_page_num": 1}
    }

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:
                mock_search.return_value = [
                    create_fake_chunk("chunk1", "doc1", "education")
                ]

                result = await search(
                    request=mock_request,
                    q="education",  # Has query = chunks mode
                    limit=50,
                    organization="UNICEF",
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
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total >= 1
    # Verify search_chunks was called
    assert mock_search.called


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_with_query_and_year():
    """Test heatmap chunks mode with query and year filter."""
    fake_db = FakeDB(search_results=[create_fake_chunk("chunk1", "doc1", "climate")])

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {
        "doc1": {
            "map_title": "Climate Report",
            "map_organization": "WHO",
            "map_published_year": "2023",
        }
    }
    mock_pg.fetch_chunks.return_value = {
        "chunk1": {"sys_text": "climate change", "sys_bbox": [], "sys_page_num": 1}
    }

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:

                mock_search.return_value = fake_db.search_results

                result = await search(
                    request=mock_request,
                    q="climate change",
                    limit=50,
                    organization=None,
                    title=None,
                    published_year="2023",
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
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total >= 1


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_with_query_and_taxonomy():
    """Test heatmap chunks mode with query and taxonomy filter."""
    fake_db = FakeDB(
        search_results=[create_fake_chunk("chunk1", "doc1", "sustainable development")]
    )

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {
        "doc1": {
            "map_title": "SDG Report",
            "map_organization": "UNICEF",
            "map_published_year": "2023",
        }
    }
    mock_pg.fetch_chunks.return_value = {
        "chunk1": {
            "sys_text": "sustainable development goals",
            "sys_bbox": [],
            "sys_page_num": 1,
        }
    }

    mock_request = Mock(spec=Request)
    mock_request.query_params = {"tag_sdg": "sdg1"}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:

                mock_search.return_value = fake_db.search_results

                result = await search(
                    request=mock_request,
                    q="sustainable development",
                    limit=50,
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
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total >= 1


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_with_mixed_filters():
    """Test heatmap chunks mode with query, regular, and taxonomy filters."""
    fake_db = FakeDB(search_results=[create_fake_chunk("chunk1", "doc1", "gender")])

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {
        "doc1": {
            "map_title": "Gender Report",
            "map_organization": "UNICEF",
            "map_published_year": "2023",
        }
    }
    mock_pg.fetch_chunks.return_value = {
        "chunk1": {"sys_text": "gender equality", "sys_bbox": [], "sys_page_num": 1}
    }

    mock_request = Mock(spec=Request)
    mock_request.query_params = {"tag_theme": "gender_equality"}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:

                mock_search.return_value = fake_db.search_results

                result = await search(
                    request=mock_request,
                    q="gender equality",
                    limit=50,
                    organization="UNICEF",
                    title=None,
                    published_year="2023",
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
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total >= 1


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_with_section_types():
    """Test heatmap chunks mode with section_types filter."""
    fake_db = FakeDB(
        search_results=[create_fake_chunk("chunk1", "doc1", "key findings")]
    )

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {
        "doc1": {
            "map_title": "Evaluation Report",
            "map_organization": "WHO",
            "map_published_year": "2023",
        }
    }
    mock_pg.fetch_chunks.return_value = {
        "chunk1": {
            "sys_text": "key findings and conclusions",
            "sys_bbox": [],
            "sys_page_num": 1,
            "tag_section_type": "findings",
        }
    }

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:

                mock_search.return_value = fake_db.search_results

                result = await search(
                    request=mock_request,
                    q="findings",
                    limit=50,
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
                    section_types="findings,recommendations",
                    keyword_boost_short_queries=True,
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total >= 1


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_heatmap_docs_mode_returns_empty_with_no_matches(mock_pg):
    """Test heatmap docs mode returns empty when no documents match filters."""
    fake_db = FakeDB(scroll_results=[])

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization="NonexistentOrg",
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 0
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_heatmap_chunks_mode_returns_empty_with_no_matches():
    """Test heatmap chunks mode returns empty when no chunks match query."""
    fake_db = FakeDB(search_results=[])

    mock_pg = Mock()
    mock_pg.fetch_docs.return_value = {}
    mock_pg.fetch_chunks.return_value = {}

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            with patch("ui.backend.routes.search.search_chunks") as mock_search:

                mock_search.return_value = fake_db.search_results

                result = await search(
                    request=mock_request,
                    q="nonexistent query",
                    limit=50,
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
                    data_source="uneg",
                    min_chunk_size=0,
                    model=None,
                    rerank_model=None,
                )

    assert result.total == 0
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_heatmap_docs_mode_with_multiple_taxonomy_filters(mock_pg):
    """Test heatmap docs mode with multiple taxonomy filters."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Comprehensive Report", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {
        "tag_sdg": "sdg4",
        "tag_theme": "education",
        "tag_country": "Kenya",
    }

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=50,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    # Verify all taxonomy filters were processed
    assert len(fake_db._scroll_calls) == 1
