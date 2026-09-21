"""Content moderation: hidden documents leave every user-facing path.

Covers the storage helper (``pipeline.db.moderation``), the write path
(``moderation.set_document_hidden``), each query path that must exclude
hidden documents (chunk search filter, document scroll, facets, title
scroll, PostgreSQL listing and facet SQL), the by-id routes that must
answer 404, the MCP document tool, and the superuser moderation routes.
"""

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException
from qdrant_client.http import models

from pipeline.db import moderation
from pipeline.db.database import Database
from pipeline.db.moderation import (
    HIDDEN_FIELD,
    HIDDEN_SQL_CLAUSE,
    exclude_hidden,
    hidden_condition,
    is_hidden,
    set_document_hidden,
)
from pipeline.db.postgres_client_docs import PostgresDocMixin
from ui.backend.services import search as search_service
from ui.backend.utils import facet_helpers
from ui.backend.utils.document_utils import normalize_document_payload

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper module
# ---------------------------------------------------------------------------


class TestHelper:
    def test_hidden_condition_targets_the_flag(self):
        cond = hidden_condition()
        assert cond.key == HIDDEN_FIELD
        assert cond.match.value is True

    def test_exclude_hidden_when_no_filter_then_only_must_not(self):
        flt = exclude_hidden(None)
        assert flt.must is None
        assert [c.key for c in flt.must_not] == [HIDDEN_FIELD]

    def test_exclude_hidden_when_filter_then_keeps_must_and_adds_must_not(self):
        base = models.Filter(
            must=[
                models.FieldCondition(
                    key="map_organization", match=models.MatchValue(value="UNDP")
                )
            ]
        )
        flt = exclude_hidden(base)
        assert flt.must == base.must
        assert [c.key for c in flt.must_not] == [HIDDEN_FIELD]
        # input untouched
        assert base.must_not is None

    def test_exclude_hidden_is_idempotent(self):
        flt = exclude_hidden(exclude_hidden(None))
        assert len(flt.must_not) == 1

    def test_exclude_hidden_keeps_existing_must_not(self):
        base = models.Filter(
            must_not=[
                models.FieldCondition(
                    key="is_duplicate", match=models.MatchValue(value=True)
                )
            ]
        )
        flt = exclude_hidden(base)
        assert [c.key for c in flt.must_not] == ["is_duplicate", HIDDEN_FIELD]

    @pytest.mark.parametrize(
        "doc, expected",
        [
            (None, False),
            ({}, False),
            ({"sys_data": {"sys_toc_approved": True}}, False),
            ({"sys_data": {HIDDEN_FIELD: True}}, True),
            ({"sys_data": {HIDDEN_FIELD: False}}, False),
            ({HIDDEN_FIELD: True}, True),
            ({"hidden": True}, True),
            ({"hidden": "true"}, False),
        ],
    )
    def test_is_hidden(self, doc, expected):
        assert is_hidden(doc) is expected

    def test_sql_clause_keeps_unflagged_rows(self):
        assert HIDDEN_SQL_CLAUSE == "(sys_data ->> 'sys_hidden')::boolean IS NOT TRUE"


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def _bare_database() -> Database:
    db = Database.__new__(Database)
    db.client = MagicMock()
    db.pg = MagicMock()
    db.documents_collection = "documents_test"
    db.chunks_collection = "chunks_test"
    return db


class TestSetDocumentHidden:
    def test_hide_writes_postgres_and_both_qdrant_collections(self):
        db = _bare_database()

        set_document_hidden(db, "42", True, reason="copyright", actor="admin@x.org")

        kwargs = db.pg.merge_doc_sys_fields.call_args.kwargs
        assert kwargs["doc_id"] == "42"
        fields = kwargs["sys_fields"]
        assert fields[HIDDEN_FIELD] is True
        assert fields[moderation.HIDDEN_REASON_FIELD] == "copyright"
        assert fields[moderation.HIDDEN_BY_FIELD] == "admin@x.org"
        assert isinstance(fields[moderation.HIDDEN_AT_FIELD], float)

        calls = db.client.set_payload.call_args_list
        assert len(calls) == 2
        doc_call, chunk_call = calls[0].kwargs, calls[1].kwargs
        assert doc_call["collection_name"] == "documents_test"
        assert doc_call["payload"] == {HIDDEN_FIELD: True}
        assert doc_call["points"] == [42]  # numeric ids are ints in Qdrant
        assert chunk_call["collection_name"] == "chunks_test"
        assert chunk_call["payload"] == {HIDDEN_FIELD: True}
        cond = chunk_call["points"].must[0]
        assert cond.key == "doc_id" and cond.match.value == "42"

    def test_restore_clears_flag_but_keeps_history(self):
        db = _bare_database()

        set_document_hidden(db, "abc-uuid", False)

        fields = db.pg.merge_doc_sys_fields.call_args.kwargs["sys_fields"]
        assert fields == {HIDDEN_FIELD: False}
        doc_call = db.client.set_payload.call_args_list[0].kwargs
        assert doc_call["points"] == ["abc-uuid"]
        assert doc_call["payload"] == {HIDDEN_FIELD: False}

    def test_payload_index_covers_the_flag(self):
        db = _bare_database()
        db._load_pipeline_config = lambda: {}
        db._load_datasource_config = lambda: {}

        db.create_payload_indexes()

        indexed = {
            (c.kwargs["collection_name"], c.kwargs["field_name"])
            for c in db.client.create_payload_index.call_args_list
        }
        assert ("documents_test", HIDDEN_FIELD) in indexed
        assert ("chunks_test", HIDDEN_FIELD) in indexed


# ---------------------------------------------------------------------------
# Query paths
# ---------------------------------------------------------------------------


def _must_not_keys(flt: Optional[models.Filter]):
    return [c.key for c in (flt.must_not or [])] if flt else []


class TestQueryPaths:
    def test_chunk_search_filter_always_excludes_hidden(self):
        flt = search_service._build_query_filter(None, None, "uneg")
        assert _must_not_keys(flt) == [HIDDEN_FIELD]

        flt = search_service._build_query_filter(
            {"organization": "UNDP"}, ["body"], "uneg"
        )
        assert _must_not_keys(flt) == [HIDDEN_FIELD]
        assert flt.must  # existing conditions kept

    def test_search_chunks_sends_exclusion_to_qdrant(self):
        dense = MagicMock()
        dense.embed.return_value = [np.array([0.2, 0.1, 0.4])]
        sparse_vec = SimpleNamespace(indices=np.array([1]), values=np.array([0.5]))
        sparse = MagicMock()
        sparse.embed.return_value = [sparse_vec]
        db = MagicMock()
        db.chunks_collection = "chunks_test"
        db.client.query_points.return_value = SimpleNamespace(points=[])
        with patch(
            "ui.backend.services.search.get_dense_model", return_value=dense
        ), patch("ui.backend.services.search.get_sparse_model", return_value=sparse):
            search_service.search_chunks(query="governance", dense_weight=1.0, db=db)
        query_filter = db.client.query_points.call_args.kwargs["query_filter"]
        assert _must_not_keys(query_filter) == [HIDDEN_FIELD]

    def test_document_scroll_excludes_hidden(self):
        db = _bare_database()
        db.client.scroll.return_value = ([], None)
        base = models.Filter(
            must=[
                models.FieldCondition(key="map_title", match=models.MatchText(text="x"))
            ]
        )

        db._scroll_documents(base, end_idx=10)

        sent = db.client.scroll.call_args.kwargs["scroll_filter"]
        assert sent.must == base.must
        assert _must_not_keys(sent) == [HIDDEN_FIELD]

    def test_facet_excludes_hidden_even_without_a_filter(self):
        db = _bare_database()
        db.client.facet.return_value = SimpleNamespace(hits=[])

        db.facet_documents("map_organization")

        sent = db.client.facet.call_args.kwargs["facet_filter"]
        assert _must_not_keys(sent) == [HIDDEN_FIELD]

    def test_title_scroll_excludes_hidden(self):
        db = MagicMock()
        db.client.scroll.return_value = ([], None)

        search_service._scroll_title_batch(db, "documents_test", None, 50, None)

        sent = db.client.scroll.call_args.kwargs["scroll_filter"]
        assert _must_not_keys(sent) == [HIDDEN_FIELD]

    def test_facet_values_search_excludes_hidden(self):
        db = MagicMock()
        db.documents_collection = "documents_test"
        db.client.facet.return_value = SimpleNamespace(hits=[])

        search_service.search_facet_values(
            "organization", "", db=db, data_source="uneg"
        )

        sent = db.client.facet.call_args.kwargs["facet_filter"]
        assert _must_not_keys(sent) == [HIDDEN_FIELD]

    def test_pg_facet_sql_excludes_hidden(self):
        pg = MagicMock()
        pg.docs_table = "docs_test"
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn = pg._get_conn.return_value.__enter__.return_value
        conn.cursor.return_value.__enter__.return_value = cur

        facet_helpers.build_facets_from_pg(pg, "sys_language")
        assert HIDDEN_SQL_CLAUSE in cur.execute.call_args.args[0]

        facet_helpers.build_facets_from_pg_jsonb(pg, "Evaluation category")
        assert HIDDEN_SQL_CLAUSE in cur.execute.call_args.args[0]


# ---------------------------------------------------------------------------
# PostgreSQL listing
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_client():
    with patch.object(PostgresDocMixin, "__init__", lambda self: None):
        c = PostgresDocMixin.__new__(PostgresDocMixin)
        c.docs_table = "docs_test"
        c.data_source = "test"
        return c


class TestListingSql:
    def test_default_listing_excludes_hidden(self, pg_client):
        clauses, params = pg_client._build_filter_clauses({}, {})
        assert clauses == [HIDDEN_SQL_CLAUSE]
        assert params == []

    def test_include_hidden_lifts_the_exclusion(self, pg_client):
        clauses, _ = pg_client._build_filter_clauses({"include_hidden": True}, {})
        assert HIDDEN_SQL_CLAUSE not in clauses
        assert "include_hidden" not in " ".join(clauses)

    def test_hidden_only_filter(self, pg_client):
        clauses, _ = pg_client._build_filter_clauses(
            {"include_hidden": True, "hidden": True}, {}
        )
        assert clauses == ["(sys_data ->> 'sys_hidden')::boolean IS TRUE"]

    def test_exclusion_coexists_with_other_filters(self, pg_client):
        clauses, params = pg_client._build_filter_clauses(
            {"title": "girls"}, {"organization": "map_organization"}
        )
        assert clauses[0] == HIDDEN_SQL_CLAUSE
        assert clauses[1] == "map_title ILIKE %s"
        assert params == ["%girls%"]


def test_normalize_exposes_hidden_fields():
    doc = normalize_document_payload(
        {"sys_hidden": True, "sys_hidden_reason": "copyright", "map_title": "T"}
    )
    assert doc["hidden"] is True
    assert doc["hidden_reason"] == "copyright"


# ---------------------------------------------------------------------------
# By-id routes and the MCP tool
# ---------------------------------------------------------------------------


def _hidden_doc() -> Dict[str, Any]:
    return {"doc_id": "d1", "map_title": "Hidden one", "sys_data": {HIDDEN_FIELD: True}}


class _Pg:
    def __init__(self, doc):
        self._doc = doc

    def fetch_docs(self, ids):
        return {"d1": dict(self._doc)} if self._doc else {}

    def fetch_chunks_for_doc(self, doc_id):
        return [{"page_num": 1, "sys_bbox": [[0, 0, 1, 1]], "text": "x"}]


class TestByIdRoutes:
    @pytest.mark.asyncio
    async def test_get_document_hidden_is_404(self, monkeypatch):
        from ui.backend.routes import documents as routes

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(_hidden_doc()))
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: None)
        with pytest.raises(HTTPException) as exc:
            await routes.get_document("d1", data_source="uneg")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_document_visible_is_returned(self, monkeypatch):
        from ui.backend.routes import documents as routes

        visible = {"doc_id": "d1", "map_title": "Fine", "sys_data": {}}
        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(visible))
        result = await routes.get_document("d1", data_source="uneg")
        assert result["title"] == "Fine"
        assert not result.get("hidden")

    @pytest.mark.asyncio
    async def test_pdf_hidden_is_404(self, monkeypatch):
        from ui.backend.routes import documents as routes

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(_hidden_doc()))
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: None)
        with pytest.raises(HTTPException) as exc:
            await routes.serve_pdf("d1", data_source="uneg")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_chunks_hidden_is_404(self, monkeypatch):
        from ui.backend.routes import documents as routes

        db = SimpleNamespace(client=MagicMock(), chunks_collection="chunks")
        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(_hidden_doc()))
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: db)
        with pytest.raises(HTTPException) as exc:
            await routes.get_document_chunks("d1", data_source="uneg")
        assert exc.value.status_code == 404
        db.client.scroll.assert_not_called()

    @pytest.mark.asyncio
    async def test_highlights_hidden_are_empty(self, monkeypatch):
        from ui.backend.routes import highlight as routes

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(_hidden_doc()))
        result = await routes.get_highlights("d1", data_source="uneg")
        assert result.highlights == [] and result.total == 0

    @pytest.mark.asyncio
    async def test_mcp_get_document_hidden_raises(self, monkeypatch):
        from mcp_server.tools import document as tool

        monkeypatch.setattr(
            "ui.backend.utils.app_state.get_pg_for_source", lambda _: _Pg(_hidden_doc())
        )
        with pytest.raises(ValueError, match="not found"):
            await tool.mcp_get_document("d1", data_source="uneg")

    @pytest.mark.asyncio
    async def test_listing_passes_include_hidden_only_for_superusers(self, monkeypatch):
        from ui.backend.routes import documents as routes

        captured: Dict[str, Any] = {}

        class _PgList:
            def get_paginated_documents(self, **kwargs):
                captured.update(kwargs)
                return {"documents": [], "total": 0, "total_pages": 0}

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _PgList())
        common = dict(
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
            data_source="uneg",
            target_language=None,
            toc_approved=None,
            sdg=None,
            cross_cutting_theme=None,
            ocr_applied=None,
            sort_by="year",
            order="desc",
        )
        await routes.get_documents(
            include_hidden=True, hidden=None, user=None, **common
        )
        assert "include_hidden" not in captured["filters"]

        admin = SimpleNamespace(is_superuser=True)
        await routes.get_documents(
            include_hidden=True, hidden=True, user=admin, **common
        )
        assert captured["filters"]["include_hidden"] is True
        assert captured["filters"]["hidden"] is True


# ---------------------------------------------------------------------------
# Moderation routes
# ---------------------------------------------------------------------------


class TestModerationRoutes:
    @pytest.mark.asyncio
    async def test_hide_writes_flag_and_audit(self, monkeypatch):
        from ui.backend.routes import moderation as routes

        db = MagicMock()
        visible = {"doc_id": "d1", "map_title": "Doc", "sys_data": {}}
        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(visible))
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: db)
        apply_hidden = MagicMock()
        monkeypatch.setattr(routes, "apply_hidden", apply_hidden)
        audit = AsyncMock()
        monkeypatch.setattr(routes, "write_audit_event", audit)
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@x.org")
        request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"))

        result = await routes.set_document_hidden.__wrapped__(
            request,
            "d1",
            routes.HideDocumentRequest(hidden=True, reason="  copyright  "),
            data_source="uneg",
            admin=admin,
        )

        apply_hidden.assert_called_once_with(
            db, "d1", True, reason="copyright", actor="admin@x.org"
        )
        assert result == {
            "doc_id": "d1",
            "hidden": True,
            "reason": "copyright",
            "was_hidden": False,
        }
        event, kwargs = audit.call_args.args[0], audit.call_args.kwargs
        assert event == routes.EVENT_DOCUMENT_HIDDEN
        assert kwargs["user_email"] == "admin@x.org"
        assert kwargs["details"]["doc_id"] == "d1"
        assert kwargs["details"]["reason"] == "copyright"

    @pytest.mark.asyncio
    async def test_restore_logs_restored_event(self, monkeypatch):
        from ui.backend.routes import moderation as routes

        db = MagicMock()
        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(_hidden_doc()))
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: db)
        apply_hidden = MagicMock()
        monkeypatch.setattr(routes, "apply_hidden", apply_hidden)
        audit = AsyncMock()
        monkeypatch.setattr(routes, "write_audit_event", audit)
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@x.org")
        request = SimpleNamespace(client=None)

        result = await routes.set_document_hidden.__wrapped__(
            request,
            "d1",
            routes.HideDocumentRequest(hidden=False),
            data_source="uneg",
            admin=admin,
        )

        apply_hidden.assert_called_once_with(
            db, "d1", False, reason=None, actor="admin@x.org"
        )
        assert result["was_hidden"] is True
        assert audit.call_args.args[0] == routes.EVENT_DOCUMENT_RESTORED

    @pytest.mark.asyncio
    async def test_unknown_document_is_404(self, monkeypatch):
        from ui.backend.routes import moderation as routes

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _Pg(None))
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@x.org")
        with pytest.raises(HTTPException) as exc:
            await routes.set_document_hidden.__wrapped__(
                SimpleNamespace(client=None),
                "nope",
                routes.HideDocumentRequest(hidden=True),
                data_source="uneg",
                admin=admin,
            )
        assert exc.value.status_code == 404

    def test_reason_is_length_limited(self):
        from ui.backend.routes import moderation as routes

        with pytest.raises(Exception):
            routes.HideDocumentRequest(hidden=True, reason="x" * 501)

    @pytest.mark.asyncio
    async def test_list_hidden_queries_only_hidden(self, monkeypatch):
        from ui.backend.routes import moderation as routes

        captured: Dict[str, Any] = {}

        class _PgList:
            def get_paginated_documents(self, **kwargs):
                captured.update(kwargs)
                return {
                    "documents": [{"sys_hidden": True, "map_title": "H"}],
                    "total": 1,
                }

        monkeypatch.setattr(routes, "get_pg_for_source", lambda _: _PgList())
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@x.org")
        result = await routes.list_hidden_documents.__wrapped__(
            SimpleNamespace(client=None),
            data_source="uneg",
            page=1,
            page_size=50,
            admin=admin,
        )
        assert captured["filters"] == {"include_hidden": True, "hidden": True}
        assert result["documents"][0]["hidden"] is True

    def test_router_is_mounted_under_user_module(self):
        import inspect

        from ui.backend import main as main_module

        src = inspect.getsource(main_module)
        assert 'moderation_routes.router, prefix="/moderation"' in src
