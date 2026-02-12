"""
Unit tests for /docsearch endpoint.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import Request

from ui.backend.routes.search import docsearch


class FakeDB:
    """Fake database for testing."""

    def __init__(self, scroll_results=None):
        self.scroll_results = scroll_results or []
        self.documents_collection = "documents_uneg"
        self._scroll_calls = []

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


@pytest.mark.asyncio
async def test_docsearch_empty_query_with_filters():
    """Test docsearch with empty query and filters returns filtered documents."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Report 2023", "UNICEF", "2023"),
            create_fake_document("2", "Study 2023", "WHO", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            # Mock threadpool to directly call the function
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=10,
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
    assert result.results[0].title == "Report 2023"
    assert result.results[1].title == "Study 2023"
    assert result.query == ""


@pytest.mark.asyncio
async def test_docsearch_with_query_searches_title_and_summary():
    """Test docsearch with query searches in title and summary fields."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Education Report", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="education",
                limit=10,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    assert len(result.results) == 1
    assert "education" in result.results[0].title.lower()
    # Verify _search_conditions was called with the query
    assert len(fake_db._scroll_calls) == 1


@pytest.mark.asyncio
async def test_docsearch_respects_limit():
    """Test docsearch respects the limit parameter."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Doc 1", "Org A", "2023"),
            create_fake_document("2", "Doc 2", "Org B", "2023"),
            create_fake_document("3", "Doc 3", "Org C", "2023"),
            create_fake_document("4", "Doc 4", "Org D", "2023"),
            create_fake_document("5", "Doc 5", "Org E", "2023"),
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
                limit=3,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 3
    assert len(result.results) == 3
    assert fake_db._scroll_calls[0]["end_idx"] == 3


@pytest.mark.asyncio
async def test_docsearch_with_taxonomy_filters():
    """Test docsearch accepts taxonomy filters from query params."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "SDG Report", "UNICEF", "2023"),
        ]
    )

    mock_request = Mock(spec=Request)
    mock_request.query_params = {"tag_sdg": "sdg4", "tag_theme": "education"}

    with patch("ui.backend.routes.search.get_db_for_source", return_value=fake_db):
        with patch("ui.backend.routes.search.run_in_threadpool") as mock_threadpool:
            mock_threadpool.side_effect = lambda func, **kwargs: func(**kwargs)

            result = await docsearch(
                request=mock_request,
                q="",
                limit=10,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    # Verify scroll was called (taxonomy filters should be included)
    assert len(fake_db._scroll_calls) == 1


@pytest.mark.asyncio
async def test_docsearch_with_organization_filter():
    """Test docsearch filters by organization."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "UNICEF Report", "UNICEF", "2023"),
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
                limit=10,
                organization="UNICEF",
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    assert result.results[0].organization == "UNICEF"


@pytest.mark.asyncio
async def test_docsearch_returns_document_level_results():
    """Test docsearch returns document-level results with proper structure."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document(
                "doc123", "Test Report", "Test Org", "2023", "Full summary text here"
            ),
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
                limit=10,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 1
    doc_result = result.results[0]
    # Check document-level result structure
    assert doc_result.chunk_id == "doc123"
    assert doc_result.doc_id == "doc123"
    assert doc_result.title == "Test Report"
    assert doc_result.organization == "Test Org"
    assert doc_result.year == "2023"
    assert doc_result.score == 1.0  # No scoring for filter-only
    assert doc_result.page_num == 1
