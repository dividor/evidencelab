"""
Unit tests for /docsearch endpoint and helper functions.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import Request
from qdrant_client.http import models as qmodels

from ui.backend.routes.search import (
    _build_docsearch_filters,
    _build_metadata_filter_condition,
    _format_document_result,
    _get_indexed_doc_ids,
    docsearch,
)


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
    assert doc_result.score == 0.0  # No scoring for filter-only
    assert doc_result.page_num == 1


# Tests for helper functions


def test_get_indexed_doc_ids_returns_list_of_doc_ids():
    """Test _get_indexed_doc_ids fetches indexed documents from Postgres."""
    mock_pg = Mock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(1,), (2,), (3,)]

    mock_conn_context = MagicMock()
    mock_conn_context.__enter__ = MagicMock(
        return_value=MagicMock(
            cursor=MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=mock_cursor), __exit__=MagicMock()
                )
            )
        )
    )
    mock_conn_context.__exit__ = MagicMock()
    mock_pg._get_conn.return_value = mock_conn_context

    result = _get_indexed_doc_ids(mock_pg, "uneg")

    assert result == ["1", "2", "3"]
    mock_cursor.execute.assert_called_once_with(
        "SELECT doc_id FROM docs_uneg WHERE sys_status = 'indexed'"
    )


def test_get_indexed_doc_ids_returns_empty_list_when_no_indexed_docs():
    """Test _get_indexed_doc_ids returns empty list when no indexed documents."""
    mock_pg = Mock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    mock_conn_context = MagicMock()
    mock_conn_context.__enter__ = MagicMock(
        return_value=MagicMock(
            cursor=MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=mock_cursor), __exit__=MagicMock()
                )
            )
        )
    )
    mock_conn_context.__exit__ = MagicMock()
    mock_pg._get_conn.return_value = mock_conn_context

    result = _get_indexed_doc_ids(mock_pg, "uneg")

    assert result == []


def test_build_metadata_filter_condition_title_uses_match_text():
    """Test _build_metadata_filter_condition uses MatchText for title field."""
    result = _build_metadata_filter_condition("title", "Education", "map_title")

    assert isinstance(result, qmodels.Filter)
    assert len(result.should) == 1
    assert result.should[0].key == "map_title"
    assert isinstance(result.should[0].match, qmodels.MatchText)
    assert result.should[0].match.text == "Education"


def test_build_metadata_filter_condition_taxonomy_extracts_code():
    """Test _build_metadata_filter_condition extracts code from taxonomy value."""
    result = _build_metadata_filter_condition(
        "tag_sdg", "sdg4 - Quality Education", "tag_sdg"
    )

    assert isinstance(result, qmodels.Filter)
    assert len(result.must) == 1
    assert result.must[0].key == "tag_sdg"
    assert isinstance(result.must[0].match, qmodels.MatchAny)
    assert result.must[0].match.any == ["sdg4"]


def test_build_metadata_filter_condition_taxonomy_without_label():
    """Test _build_metadata_filter_condition handles taxonomy code without label."""
    result = _build_metadata_filter_condition("tag_theme", "education", "tag_theme")

    assert isinstance(result, qmodels.Filter)
    assert len(result.must) == 1
    assert result.must[0].match.any == ["education"]


def test_build_metadata_filter_condition_standard_field_uses_match_value():
    """Test _build_metadata_filter_condition uses MatchValue for standard fields."""
    result = _build_metadata_filter_condition(
        "organization", "UNICEF", "map_organization"
    )

    assert isinstance(result, qmodels.Filter)
    assert len(result.must) == 1
    assert result.must[0].key == "map_organization"
    assert isinstance(result.must[0].match, qmodels.MatchValue)
    assert result.must[0].match.value == "UNICEF"


def test_build_docsearch_filters_includes_query_conditions():
    """Test _build_docsearch_filters includes search conditions when query provided."""
    mock_db = Mock()
    mock_db._search_conditions.return_value = [
        qmodels.FieldCondition(key="map_title", match=qmodels.MatchText(text="test"))
    ]

    result = _build_docsearch_filters("test query", {}, ["1", "2"], mock_db)

    assert isinstance(result, qmodels.Filter)
    assert len(result.must) >= 2  # At least query filter and indexed_doc_ids filter
    mock_db._search_conditions.assert_called_once_with("test query")


def test_build_docsearch_filters_skips_empty_query():
    """Test _build_docsearch_filters skips search conditions when query is empty."""
    mock_db = Mock()

    with patch(
        "ui.backend.routes.search.map_core_field_to_storage", return_value="map_org"
    ):
        result = _build_docsearch_filters(
            "", {"organization": "UNICEF"}, ["1", "2"], mock_db
        )

    assert isinstance(result, qmodels.Filter)
    mock_db._search_conditions.assert_not_called()


def test_build_docsearch_filters_skips_none_values():
    """Test _build_docsearch_filters skips filters with None values."""
    mock_db = Mock()
    mock_db._search_conditions.return_value = []

    with patch("ui.backend.routes.search.map_core_field_to_storage") as mock_map_field:
        mock_map_field.return_value = "map_org"
        result = _build_docsearch_filters(
            "", {"organization": None, "title": "Test"}, ["1"], mock_db
        )

    # Only title should be processed, not organization
    assert isinstance(result, qmodels.Filter)


def test_build_docsearch_filters_includes_indexed_doc_ids():
    """Test _build_docsearch_filters includes indexed doc IDs filter."""
    mock_db = Mock()
    mock_db._search_conditions.return_value = []
    indexed_ids = ["1", "2", "3"]

    result = _build_docsearch_filters("", {}, indexed_ids, mock_db)

    assert isinstance(result, qmodels.Filter)
    # Find the HasIdCondition in the filters
    has_id_filter = None
    for filter_item in result.must:
        if hasattr(filter_item, "should") and filter_item.should:
            for cond in filter_item.should:
                if isinstance(cond, qmodels.HasIdCondition):
                    has_id_filter = cond
                    break

    assert has_id_filter is not None
    assert has_id_filter.has_id == indexed_ids


def test_format_document_result_returns_none_for_empty_payload():
    """Test _format_document_result returns None when point has no payload."""
    point = SimpleNamespace(id="123", payload=None)

    result = _format_document_result(point, {}, "uneg")

    assert result is None


def test_format_document_result_formats_document_correctly():
    """Test _format_document_result creates proper SearchResult."""
    point = SimpleNamespace(
        id="doc123",
        payload={
            "map_title": "Test Report",
            "map_organization": "UNICEF",
            "map_published_year": 2023,
            "sys_full_summary": "This is a long summary " * 50,  # > 500 chars
        },
    )
    sys_fields = {
        "sys_parsed_folder": "/data/parsed/uneg/doc123",
        "sys_filepath": "/data/raw/uneg/doc123.pdf",
    }

    with patch("ui.backend.routes.search.normalize_document_payload") as mock_normalize:
        mock_normalize.return_value = {
            "title": "Test Report",
            "organization": "UNICEF",
            "published_year": "2023",  # String, not int
            "sys_full_summary": point.payload["sys_full_summary"],
            "metadata": {},
            "sys_parsed_folder": sys_fields["sys_parsed_folder"],
            "sys_filepath": sys_fields["sys_filepath"],
        }

        result = _format_document_result(point, {"doc123": sys_fields}, "uneg")

    assert result is not None
    assert result.chunk_id == "doc123"
    assert result.doc_id == "doc123"
    assert result.title == "Test Report"
    assert result.organization == "UNICEF"
    assert result.year == "2023"  # String, not int
    assert result.score == 0.0
    assert result.page_num == 1
    assert len(result.headings) == 0
    assert len(result.text) <= 500  # Text should be truncated
    assert result.data_source == "uneg"
    assert result.sys_parsed_folder == sys_fields["sys_parsed_folder"]
    assert result.sys_filepath == sys_fields["sys_filepath"]


def test_format_document_result_merges_sys_fields_from_postgres():
    """Test _format_document_result merges sys fields from Postgres."""
    point = SimpleNamespace(
        id="doc456",
        payload={"map_title": "Report", "map_organization": "WHO"},
    )
    sys_fields_map = {
        "doc456": {"sys_parsed_folder": "/data/parsed", "sys_custom_field": "value"}
    }

    with patch("ui.backend.routes.search.normalize_document_payload") as mock_normalize:
        mock_normalize.return_value = {
            "title": "Report",
            "organization": "WHO",
            "sys_parsed_folder": "/data/parsed",
            "metadata": {},
        }

        _format_document_result(point, sys_fields_map, "uneg")

    # Verify normalize_document_payload was called with merged data
    call_args = mock_normalize.call_args[0][0]
    assert "doc_id" in call_args
    assert call_args["doc_id"] == "doc456"
    assert "sys_parsed_folder" in call_args


@pytest.mark.asyncio
async def test_docsearch_returns_empty_when_no_indexed_documents():
    """Test docsearch returns empty response when no indexed documents exist."""
    mock_pg = Mock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []  # No indexed documents

    mock_conn_context = MagicMock()
    mock_conn_context.__enter__ = MagicMock(
        return_value=MagicMock(
            cursor=MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=mock_cursor), __exit__=MagicMock()
                )
            )
        )
    )
    mock_conn_context.__exit__ = MagicMock()
    mock_pg._get_conn.return_value = mock_conn_context

    mock_request = Mock(spec=Request)
    mock_request.query_params = {}

    with patch("ui.backend.routes.search.get_db_for_source"):
        with patch("ui.backend.routes.search.get_pg_for_source", return_value=mock_pg):
            result = await docsearch(
                request=mock_request,
                q="test",
                limit=10,
                organization=None,
                title=None,
                published_year=None,
                document_type=None,
                country=None,
                language=None,
                data_source="uneg",
            )

    assert result.total == 0
    assert len(result.results) == 0
    assert result.query == "test"


@pytest.mark.asyncio
async def test_docsearch_filters_out_documents_without_payload():
    """Test docsearch filters out documents that have no payload."""
    fake_db = FakeDB(
        scroll_results=[
            create_fake_document("1", "Valid Doc", "UNICEF", "2023"),
            SimpleNamespace(id="2", payload=None),  # No payload
            create_fake_document("3", "Another Valid", "WHO", "2023"),
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

    # Should only return 2 valid documents, filtering out the one without payload
    assert result.total == 2
    assert len(result.results) == 2
    assert result.results[0].doc_id == "1"
    assert result.results[1].doc_id == "3"
