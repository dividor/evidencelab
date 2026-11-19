"""Search results carry only the document fields readers use.

Before, every result repeated the whole document record as ``metadata``, so a
Heatmap cell with 1000 results was 143 MB and Google Cloud Run (32 MiB limit
on non-streamed responses) failed it with HTTP 500. These tests pin which keys
a result keeps in the full and the lean shape, that a data source's metadata
panel fields are always kept, and that ``limit`` above
``application.search.max_limit`` is rejected with 422.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException, Request

from pipeline.db import config as db_config
from ui.backend.routes import search as search_routes
from ui.backend.services.result_shape import (
    DROPPED_METADATA_KEYS,
    LEAN_DROPPED_CHUNK_FIELDS,
    LEAN_DROPPED_METADATA_KEYS,
    ResultShape,
)

pytestmark = pytest.mark.unit

DOC_ID = "doc-1"

# A document record as ``fetch_docs`` returns it, with every heavy key.
DOC_RECORD = {
    "id": DOC_ID,
    "map_title": "Report A",
    "map_organization": "WFP",
    "map_published_year": "2023",
    "map_country": "Kenya",
    "map_pdf_url": "https://example.org/a.pdf",
    "map_report_url": "https://example.org/a",
    "sys_parsed_folder": "data/wfp/parsed/WFP/2023/doc-1",
    "sys_filepath": "data/wfp/docs/a.pdf",
    "sys_status": "indexed",
    "sys_full_summary": "A long summary " * 50,
    "sys_toc_classified": "1. Intro [context]",
    "sys_toc": "1. Intro",
    "sys_taxonomies": {"sdg": ["SDG 2"]},
    "sys_data": {"sys_parsed_folder": "data/wfp/parsed/WFP/2023/doc-1"},
    "src_doc_raw_metadata": {"Evaluation category": "Decentralised"},
    "abstractive_summary": "short",
}

CHUNK_RECORD = {
    "sys_text": "Hello world, this is the chunk text.",
    "sys_page_num": 4,
    "sys_headings": ["Findings"],
    "sys_bbox": [[0, 0, 1, 1]],
    "sys_chunk_elements": [{"type": "text"}],
    "sys_elements": [{"type": "text"}],
    "sys_table_data": {"rows": []},
    "sys_tables": [{"rows": []}],
    "sys_images": [{"path": "img.png"}],
}

CHUNK_FIELDS = ("chunk_elements", "bbox", "elements", "table_data", "tables", "images")


def _hit(chunk_id="chunk-1"):
    return SimpleNamespace(
        id=chunk_id, score=0.9, payload={"doc_id": DOC_ID, "sys_text": "x"}
    )


def _build(shape: ResultShape):
    results = search_routes._build_search_results(
        [_hit()],
        {DOC_ID: dict(DOC_RECORD)},
        {"chunk-1": dict(CHUNK_RECORD)},
        "wfp",
        10,
        0,
        shape,
    )
    assert len(results) == 1
    return results[0]


class TestFullShape:
    def test_metadata_keeps_fields_readers_use(self):
        meta = _build(ResultShape()).metadata
        for key in (
            "title",
            "organization",
            "published_year",
            "country",
            "map_title",
            "map_country",
            "pdf_url",
            "report_url",
            "src_evaluation_category",
            "sys_parsed_folder",
            "parsed_folder",
            "sys_filepath",
            "status",
            "full_summary",
            "toc_classified",
            "id",
        ):
            assert key in meta, key
        assert meta["pdf_url"] == DOC_RECORD["map_pdf_url"]
        assert meta["full_summary"] == DOC_RECORD["sys_full_summary"]

    def test_metadata_drops_record_blobs_and_sys_twins(self):
        meta = _build(ResultShape()).metadata
        for key in DROPPED_METADATA_KEYS:
            assert key not in meta, key
        assert "sys_data" not in meta
        assert "src_doc_raw_metadata" not in meta
        assert "sys_full_summary" not in meta
        assert "sys_toc_classified" not in meta

    def test_chunk_fields_present(self):
        result = _build(ResultShape())
        assert result.chunk_elements == CHUNK_RECORD["sys_chunk_elements"]
        assert result.tables == CHUNK_RECORD["sys_tables"]
        assert result.table_data == CHUNK_RECORD["sys_table_data"]
        assert result.images == CHUNK_RECORD["sys_images"]
        assert result.bbox == CHUNK_RECORD["sys_bbox"]
        assert result.elements == CHUNK_RECORD["sys_elements"]

    def test_keep_keys_override_the_drop_list(self):
        meta = _build(ResultShape(keep_keys=frozenset({"taxonomies"}))).metadata
        assert meta["taxonomies"] == DOC_RECORD["sys_taxonomies"]
        assert "sys_taxonomies" not in meta


class TestLeanShape:
    def test_no_chunk_level_data(self):
        result = _build(ResultShape(lean=True))
        assert set(CHUNK_FIELDS) == LEAN_DROPPED_CHUNK_FIELDS
        for field in CHUNK_FIELDS:
            assert getattr(result, field) is None, field
        # What a list and a text export need stays.
        assert result.text
        assert result.page_num == 4
        assert result.headings == ["Findings"]
        assert result.title == "Report A"

    def test_no_document_texts_in_metadata(self):
        meta = _build(ResultShape(lean=True)).metadata
        for key in DROPPED_METADATA_KEYS | LEAN_DROPPED_METADATA_KEYS:
            assert key not in meta, key
        assert "full_summary" not in meta
        assert "toc_classified" not in meta
        for key in ("title", "pdf_url", "sys_parsed_folder", "src_evaluation_category"):
            assert key in meta, key

    def test_lean_drops_document_texts_even_when_panel_fields(self):
        shape = ResultShape(lean=True, keep_keys=frozenset({"full_summary"}))
        assert "full_summary" not in _build(shape).metadata


class TestForSource:
    def test_panel_fields_are_kept(self):
        panel = {"title": "Title", "taxonomies": "Taxonomies"}
        with patch(
            "ui.backend.services.result_shape.get_metadata_panel_fields",
            return_value=panel,
        ) as getter:
            shape = ResultShape.for_source("wfp")
        getter.assert_called_once_with("wfp")
        assert shape.keep_keys == frozenset(panel)
        assert "taxonomies" in _build(shape).metadata

    def test_extra_keep_and_lean_are_carried(self):
        with patch(
            "ui.backend.services.result_shape.get_metadata_panel_fields",
            return_value={},
        ):
            shape = ResultShape.for_source("wfp", lean=True, keep=("taxonomies",))
        assert shape.lean is True
        assert shape.keep_keys == frozenset({"taxonomies"})

    def test_no_source_means_no_panel_fields(self):
        with patch(
            "ui.backend.services.result_shape.get_metadata_panel_fields"
        ) as getter:
            shape = ResultShape.for_source(None)
        getter.assert_not_called()
        assert shape.keep_keys == frozenset()


class TestConfigHelpers:
    def test_metadata_panel_fields_of_a_data_source(self, monkeypatch):
        monkeypatch.setattr(
            db_config,
            "load_datasources_config",
            lambda: {
                "datasources": {
                    "WFP": {
                        "data_subdir": "wfp",
                        "metadata_panel_fields": {"title": "Document Title"},
                    }
                }
            },
        )
        assert db_config.get_metadata_panel_fields("wfp") == {"title": "Document Title"}
        assert db_config.get_metadata_panel_fields("other") == {}

    def test_search_max_limit_reads_config(self, monkeypatch):
        monkeypatch.setattr(
            db_config,
            "load_datasources_config",
            lambda: {"application": {"search": {"max_limit": 250}}},
        )
        assert db_config.get_search_max_limit() == 250

    def test_search_max_limit_default_when_unset(self, monkeypatch):
        monkeypatch.setattr(
            db_config, "load_datasources_config", lambda: {"application": {}}
        )
        assert db_config.get_search_max_limit() == db_config.DEFAULT_SEARCH_MAX_LIMIT


def _search_kwargs(**overrides):
    request = Mock(spec=Request)
    request.query_params = {}
    kwargs = dict(
        request=request,
        q="education",
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
        rerank_model_page_size=None,
        wide_search=False,
        wide_group_size=5,
        wide_limit=20,
        auto_min_score=False,
        deduplicate=True,
        field_boost=True,
        field_boost_fields=None,
        lean=False,
    )
    kwargs.update(overrides)
    return kwargs


class TestMaxLimit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("param", ["limit", "wide_limit"])
    async def test_above_max_limit_is_422_before_any_search(self, monkeypatch, param):
        monkeypatch.setattr(search_routes, "SEARCH_MAX_LIMIT", 100)
        with patch.object(search_routes, "get_db_for_source") as get_db:
            with pytest.raises(HTTPException) as exc_info:
                await search_routes.search(**_search_kwargs(**{param: 101}))
        assert exc_info.value.status_code == 422
        assert param in exc_info.value.detail
        assert "max_limit" in exc_info.value.detail
        get_db.assert_not_called()

    def test_at_max_limit_passes(self, monkeypatch):
        monkeypatch.setattr(search_routes, "SEARCH_MAX_LIMIT", 100)
        search_routes._check_search_limits(100, 100)

    def test_module_limit_comes_from_config(self):
        assert search_routes.SEARCH_MAX_LIMIT == db_config.get_search_max_limit()
