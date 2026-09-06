"""The paginated documents payload must surface the human-approval flag.

The TOC Validator (and the Documents Library approval checkbox) read
``toc_approved`` off each listed document. That field is derived from
``sys_data['sys_toc_approved']`` by ``_get_paginated_documents_impl`` and then
normalised to ``toc_approved`` by ``normalize_document_payload``. These tests
guard that contract so the approval indicator cannot silently regress.
"""

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from pipeline.db.postgres_client_docs import PostgresDocMixin
from ui.backend.utils.document_utils import normalize_document_payload


@pytest.fixture()
def client():
    """A PostgresDocMixin whose DB connection is fully mocked."""
    with patch.object(PostgresDocMixin, "__init__", lambda self: None):
        c = PostgresDocMixin.__new__(PostgresDocMixin)
        c.docs_table = "docs_test"
        c.data_source = "test"

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # count query
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        c._get_conn = MagicMock(return_value=mock_conn)
        c._mock_cursor = mock_cursor
        return c


def _row(sys_data: Optional[Dict[str, Any]]) -> tuple:
    """Build one result row in the exact column order the impl SELECTs."""
    return (
        "d1",  # doc_id
        {},  # src_doc_raw_metadata
        None,  # sys_summary
        None,  # sys_full_summary
        None,  # sys_taxonomies
        "indexed",  # sys_status
        None,  # sys_status_timestamp
        sys_data,  # sys_data
        None,  # sys_file_format
        None,  # sys_file_size_mb
        None,  # sys_page_count
        None,  # sys_language
        None,  # sys_stages
        None,  # sys_last_updated
        None,  # sys_error_message
        "Doc",  # map_title
        None,  # map_organization
        None,  # map_published_year
        None,  # map_document_type
        None,  # map_country
        None,  # map_language
        None,  # map_region
        None,  # map_theme
        None,  # map_pdf_url
        None,  # map_report_url
        None,  # sys_ocr_applied
    )


def _first_doc(client, sys_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    client._mock_cursor.fetchall.return_value = [_row(sys_data)]
    result = client._get_paginated_documents_impl(
        page=1,
        page_size=10,
        filters={},
        filter_map={},
        sort_by="year",
        sort_order="asc",
    )
    return result["documents"][0]


class TestPaginatedTocApproved:
    @pytest.mark.unit
    def test_approved_document_exposes_toc_approved_true(self, client):
        doc = _first_doc(client, {"sys_toc_approved": True})
        assert doc["sys_toc_approved"] is True
        assert normalize_document_payload(doc)["toc_approved"] is True

    @pytest.mark.unit
    def test_unapproved_document_reports_falsy_toc_approved(self, client):
        doc = _first_doc(client, {"sys_toc_classified": "x"})
        assert doc["sys_toc_approved"] is None
        assert normalize_document_payload(doc).get("toc_approved") is None

    @pytest.mark.unit
    def test_missing_sys_data_does_not_crash(self, client):
        doc = _first_doc(client, None)
        assert doc["sys_toc_approved"] is None
