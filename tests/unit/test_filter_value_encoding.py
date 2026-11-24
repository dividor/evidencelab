"""Filter values that contain commas.

A multi-select filter arrives as one string listing values separated by commas.
A comma inside a value is written ``\\,`` and a backslash ``\\\\``, so names such
as ``SDG16 - Peace, Justice and Strong Institutions`` survive. Regression: the
API split every filter string on commas, so a Heatmapper cell, a Search filter or
a Documents filter on SDG9 / SDG16 (or any name with a comma) matched nothing.
"""

from unittest.mock import MagicMock

import pytest
from qdrant_client.http import models as qmodels

from mcp_server.tools.search import normalize_agent_filters
from pipeline.db.postgres_client_docs import PostgresDocMixin
from ui.backend.routes.documents import _build_document_filters
from ui.backend.routes.search import (
    _build_docsearch_filters,
    _build_filters_response,
    _convert_language_to_doc_ids,
    _convert_region_to_doc_ids,
    _convert_src_fields_to_doc_ids,
    _resolve_title_doc_ids,
)
from ui.backend.services.search import _build_query_filter
from ui.backend.utils.filter_helpers import (
    expand_multivalue_filters,
    filter_match,
    parse_filter_values,
)

pytestmark = pytest.mark.unit

SDG16 = "SDG16 - Peace, Justice and Strong Institutions"
SDG16_ESCAPED = "SDG16 - Peace\\, Justice and Strong Institutions"
SDG9 = "SDG9 - Industry, Innovation and Infrastructure"
SDG9_ESCAPED = "SDG9 - Industry\\, Innovation and Infrastructure"


class TestParseFilterValues:
    def test_parse_when_plain_value_then_single_value(self):
        assert parse_filter_values("Kenya") == ["Kenya"]

    def test_parse_when_comma_separated_then_each_value(self):
        assert parse_filter_values("Kenya,Uganda, Malawi") == [
            "Kenya",
            "Uganda",
            "Malawi",
        ]

    def test_parse_when_escaped_comma_then_kept_in_value(self):
        assert parse_filter_values(SDG16_ESCAPED) == [SDG16]

    def test_parse_when_escaped_and_plain_mixed_then_split_on_plain_commas(self):
        assert parse_filter_values(f"{SDG9_ESCAPED},{SDG16_ESCAPED},SDG1") == [
            SDG9,
            SDG16,
            "SDG1",
        ]

    def test_parse_when_escaped_backslash_then_single_backslash(self):
        assert parse_filter_values("a\\\\b,c") == ["a\\b", "c"]

    def test_parse_when_lone_backslash_then_kept_literally(self):
        assert parse_filter_values("C:\\docs") == ["C:\\docs"]

    def test_parse_when_blank_parts_then_dropped(self):
        assert parse_filter_values(" , Kenya ,, ") == ["Kenya"]

    def test_parse_when_list_then_items_kept_whole(self):
        assert parse_filter_values([SDG16, " Kenya ", "", None]) == [SDG16, "Kenya"]

    def test_parse_when_none_or_empty_then_no_values(self):
        assert parse_filter_values(None) == []
        assert parse_filter_values("") == []

    def test_parse_when_number_then_kept_as_number(self):
        assert parse_filter_values(2024) == [2024]


class TestFilterMatch:
    def test_match_when_escaped_single_value_then_exact_full_name(self):
        assert filter_match(SDG16_ESCAPED) == qmodels.MatchValue(value=SDG16)

    def test_match_when_two_values_then_match_any(self):
        assert filter_match(f"{SDG9_ESCAPED},{SDG16_ESCAPED}") == qmodels.MatchAny(
            any=[SDG9, SDG16]
        )

    def test_match_when_list_of_one_then_exact_value(self):
        assert filter_match([SDG16]) == qmodels.MatchValue(value=SDG16)


def _conditions_for(query_filter, key):
    return [c for c in query_filter.must if getattr(c, "key", None) == key]


class TestChunkSearchFilter:
    def test_query_filter_when_heatmap_cell_value_has_comma_then_one_exact_match(self):
        # The Heatmapper sends the cell's column value as an escaped filter.
        query_filter = _build_query_filter({"tag_sdg": SDG16_ESCAPED}, None, "uneg")
        [condition] = _conditions_for(query_filter, "tag_sdg")
        assert condition.match == qmodels.MatchValue(value=SDG16)

    def test_query_filter_when_list_value_then_kept_whole(self):
        query_filter = _build_query_filter({"tag_sdg": [SDG9, SDG16]}, None, "uneg")
        [condition] = _conditions_for(query_filter, "tag_sdg")
        assert condition.match == qmodels.MatchAny(any=[SDG9, SDG16])

    def test_query_filter_when_title_list_then_text_match_per_title(self):
        query_filter = _build_query_filter(
            {"title": ["Evaluation, 2016-2020", "Other"]}, None, "uneg"
        )
        title_filter = next(
            c for c in query_filter.must if isinstance(c, qmodels.Filter) and c.should
        )
        assert [c.match for c in title_filter.should] == [
            qmodels.MatchText(text="Evaluation, 2016-2020"),
            qmodels.MatchText(text="Other"),
        ]


class TestDocumentSearchFilter:
    def test_docsearch_filter_when_escaped_value_then_exact_full_name(self):
        db = MagicMock()
        combined = _build_docsearch_filters("", {"tag_sdg": SDG16_ESCAPED}, ["d1"], db)
        matches = [
            cond.must[0].match
            for cond in combined.must
            if getattr(cond, "must", None)
            and getattr(cond.must[0], "key", None) == "tag_sdg"
        ]
        assert matches == [qmodels.MatchValue(value=SDG16)]


class TestDocLevelFilters:
    def test_region_when_names_have_commas_then_each_name_looked_up_whole(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1"]
        core = {
            "region": "Middle East\\, Northern Africa\\, and Eastern Europe,"
            "Asia and the Pacific"
        }
        _convert_region_to_doc_ids(core, pg)
        pg.fetch_doc_ids_by_region.assert_called_once_with(
            ["Middle East, Northern Africa, and Eastern Europe", "Asia and the Pacific"]
        )
        assert core["doc_id"] == "d1"

    def test_src_field_when_value_has_comma_then_looked_up_whole(self, monkeypatch):
        captured = {}

        def fake_lookup(pg, raw_key, values):
            captured["values"] = values
            return ["d1"]

        monkeypatch.setattr(
            "ui.backend.routes.search.doc_ids_from_pg_jsonb", fake_lookup
        )
        monkeypatch.setattr(
            "ui.backend.routes.search.get_src_field_mapping",
            lambda source: {"src_theme": "theme"},
        )
        core = {"src_theme": "Peace\\, Justice,Health"}
        _convert_src_fields_to_doc_ids(core, MagicMock(), "uneg")
        assert captured["values"] == ["Peace, Justice", "Health"]

    def test_language_when_several_then_each_code_looked_up(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = ["d1"]
        core = {"language": ["en", "fr"]}
        _convert_language_to_doc_ids(core, pg)
        pg.fetch_doc_ids_by_language.assert_called_once_with(["en", "fr"])


class TestTitleFilter:
    def test_title_when_titles_have_commas_then_exact_titles_looked_up(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d1", "d2"]
        pg.fetch_doc_ids_by_title.return_value = []
        result = _resolve_title_doc_ids(
            pg, "Country evaluation\\, 2016-2020,Annual report"
        )
        pg.fetch_doc_ids_by_exact_titles.assert_called_once_with(
            ["Country evaluation, 2016-2020", "Annual report"]
        )
        assert result == ["d1", "d2"]

    def test_filters_response_when_escaped_value_then_display_values(self):
        response = _build_filters_response(
            {"tag_sdg": f"{SDG9_ESCAPED},{SDG16_ESCAPED}"}, None
        )
        assert response == {"tag_sdg": [SDG9, SDG16]}


class TestMultivalueExpansion:
    def test_expansion_when_escaped_value_then_selected_whole(self):
        db = MagicMock()
        db.documents_collection = "documents_test"
        db.indexed_payload_keys.return_value = {"map_country"}
        db.facet_documents.return_value = {
            "Congo, Dem. Rep.": 3,
            "Congo, Dem. Rep.; Rwanda": 2,
        }
        core = {"country": "Congo\\, Dem. Rep."}
        expand_multivalue_filters(db, core, "uneg")
        assert core["country"] == ["Congo, Dem. Rep.", "Congo, Dem. Rep.; Rwanda"]


class TestDocumentsTabFilters:
    def _build(self, **overrides):
        args = dict(
            organization=None,
            document_type=None,
            published_year=None,
            language=None,
            file_format=None,
            status=None,
            title=None,
            search=None,
            toc_approved=None,
            sdg=None,
            cross_cutting_theme=None,
        )
        args.update(overrides)
        return _build_document_filters(**args)

    def test_documents_when_sdg_has_comma_then_full_name_kept(self):
        assert self._build(sdg=SDG16_ESCAPED)["sdg"] == [SDG16]

    def test_documents_when_single_escaped_organization_then_plain_value(self):
        filters = self._build(organization="Office of Evaluation\\, WFP")
        assert filters["organization"] == "Office of Evaluation, WFP"

    def test_documents_when_two_organizations_then_list(self):
        filters = self._build(organization="UNDP,WFP")
        assert filters["organization"] == ["UNDP", "WFP"]

    def test_documents_when_two_titles_then_each_matched_in_postgres(self):
        filters = self._build(title="Country evaluation\\, 2016-2020,Annual report")
        assert filters["title"] == ["Country evaluation, 2016-2020", "Annual report"]
        client = PostgresDocMixin.__new__(PostgresDocMixin)
        params: list = []
        clause = client._special_clause("title", filters["title"], params, {})
        assert clause == "(map_title ILIKE %s OR map_title ILIKE %s)"
        assert params == ["%Country evaluation, 2016-2020%", "%Annual report%"]

    def test_documents_when_one_title_then_single_match(self):
        client = PostgresDocMixin.__new__(PostgresDocMixin)
        params: list = []
        clause = client._special_clause("title", "Annual report", params, {})
        assert clause == "(map_title ILIKE %s)"
        assert params == ["%Annual report%"]


class TestAgentFilters:
    def test_agent_string_when_it_has_commas_then_one_value(self):
        assert normalize_agent_filters({"tag_sdg": SDG16}) == {"tag_sdg": [SDG16]}

    def test_agent_list_then_values_kept(self):
        assert normalize_agent_filters({"tag_sdg": [SDG9, SDG16]}) == {
            "tag_sdg": [SDG9, SDG16]
        }

    def test_agent_number_and_range_then_unchanged(self):
        assert normalize_agent_filters(
            {"published_year": 2024, "published_year_min": 2020}
        ) == {"published_year": 2024, "published_year_min": 2020}

    def test_agent_no_filters_then_none(self):
        assert normalize_agent_filters(None) is None
