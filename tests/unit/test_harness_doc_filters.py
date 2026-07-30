"""Unit tests for the eval-harness document-level filter resolver.

The evaluation harness lets a test case filter by exact document title (``doc_titles``)
and by ``region`` — both document-level fields not stored on chunks. Because the
harness calls chunk search directly (bypassing the ``/search`` route's own
resolvers), these must be resolved to a ``doc_id`` filter at run time. These tests
cover that resolution, its AND-intersection with a pre-existing ``doc_id`` filter,
region OR-union, and the no-match sentinel behaviour.
"""

from unittest.mock import MagicMock

import pytest

from ui.backend.utils.filter_helpers import NO_MATCH_DOC_ID, resolve_doc_level_filters

pytestmark = pytest.mark.unit


def _pg_titles(doc_ids):
    pg = MagicMock()
    pg.fetch_doc_ids_by_exact_titles.return_value = list(doc_ids)
    return pg


class TestResolveDocTitles:
    def test_no_doc_level_keys_when_absent_then_filters_returned_unchanged(self):
        filters = {"published_year_max": 2020, "country": "Kenya"}
        pg = MagicMock()
        assert resolve_doc_level_filters(filters, pg) == {
            "published_year_max": 2020,
            "country": "Kenya",
        }
        pg.fetch_doc_ids_by_exact_titles.assert_not_called()
        pg.fetch_doc_ids_by_region.assert_not_called()

    def test_single_title_when_set_then_replaced_by_doc_id_filter(self):
        filters = {"doc_titles": ["Report A"]}
        pg = _pg_titles(["d1"])
        result = resolve_doc_level_filters(filters, pg)
        assert "doc_titles" not in result
        assert result["doc_id"] == ["d1"]
        pg.fetch_doc_ids_by_exact_titles.assert_called_once_with(["Report A"])

    def test_multiple_titles_when_set_then_all_doc_ids_returned(self):
        filters = {"doc_titles": ["Report A", "Report B"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d2", "d1"]))
        assert result["doc_id"] == ["d1", "d2"]  # sorted, deterministic

    def test_comma_string_when_given_then_split_into_titles(self):
        filters = {"doc_titles": "Report A, Report B"}
        pg = _pg_titles(["d1"])
        resolve_doc_level_filters(filters, pg)
        pg.fetch_doc_ids_by_exact_titles.assert_called_once_with(
            ["Report A", "Report B"]
        )

    def test_blank_titles_when_only_whitespace_then_no_lookup_and_no_doc_id(self):
        filters = {"doc_titles": ["  ", ""]}
        pg = MagicMock()
        result = resolve_doc_level_filters(filters, pg)
        assert "doc_titles" not in result
        assert "doc_id" not in result
        pg.fetch_doc_ids_by_exact_titles.assert_not_called()

    def test_titles_when_no_docs_match_then_sentinel_doc_id(self):
        filters = {"doc_titles": ["Nonexistent"]}
        result = resolve_doc_level_filters(filters, _pg_titles([]))
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_existing_doc_id_when_titles_set_then_intersected(self):
        filters = {"doc_titles": ["Report A"], "doc_id": "d1,d2,d3"}
        result = resolve_doc_level_filters(filters, _pg_titles(["d2", "d3", "d4"]))
        assert result["doc_id"] == ["d2", "d3"]

    def test_existing_doc_id_when_disjoint_then_sentinel(self):
        filters = {"doc_titles": ["Report A"], "doc_id": ["d1"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d9"]))
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_invalid_titles_when_not_list_or_string_then_value_error(self):
        with pytest.raises(ValueError, match="doc_titles must be a list"):
            resolve_doc_level_filters({"doc_titles": 123}, MagicMock())

    def test_input_dict_when_resolved_then_not_mutated(self):
        filters = {"doc_titles": ["Report A"], "country": "Kenya"}
        resolve_doc_level_filters(filters, _pg_titles(["d1"]))
        assert filters == {"doc_titles": ["Report A"], "country": "Kenya"}

    def test_non_dict_when_passed_then_returned_unchanged(self):
        assert resolve_doc_level_filters(None, MagicMock()) is None

    def test_country_when_set_then_left_untouched(self):
        # country is stamped on chunks and applied natively — never resolved here.
        filters = {"country": ["Kenya"], "doc_titles": ["Report A"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d1"]))
        assert result["country"] == ["Kenya"]
        assert result["doc_id"] == ["d1"]


class TestResolveRegion:
    def test_single_region_when_set_then_resolved_to_doc_ids(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1", "d2"]
        result = resolve_doc_level_filters({"region": "Asia and the Pacific"}, pg)
        assert "region" not in result
        assert result["doc_id"] == ["d1", "d2"]
        pg.fetch_doc_ids_by_region.assert_called_once_with("Asia and the Pacific")

    def test_region_list_when_set_then_doc_ids_are_unioned(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.side_effect = [["d1", "d2"], ["d2", "d3"]]
        result = resolve_doc_level_filters(
            {"region": ["Asia and the Pacific", "Eastern Africa"]}, pg
        )
        assert result["doc_id"] == ["d1", "d2", "d3"]  # union, sorted
        assert pg.fetch_doc_ids_by_region.call_count == 2

    def test_region_name_with_comma_when_string_then_not_split(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1"]
        resolve_doc_level_filters(
            {"region": "Middle East, Northern Africa, and Eastern Europe"}, pg
        )
        pg.fetch_doc_ids_by_region.assert_called_once_with(
            "Middle East, Northern Africa, and Eastern Europe"
        )

    def test_region_when_no_docs_match_then_sentinel_doc_id(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = []
        result = resolve_doc_level_filters({"region": ["Nowhere"]}, pg)
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_invalid_region_when_not_list_or_string_then_value_error(self):
        with pytest.raises(ValueError, match="region must be a string or a list"):
            resolve_doc_level_filters({"region": 5}, MagicMock())


class TestResolveTitlesAndRegionCombined:
    def test_titles_and_region_when_both_set_then_intersected(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d1", "d2", "d3"]
        pg.fetch_doc_ids_by_region.return_value = ["d2", "d3", "d4"]
        result = resolve_doc_level_filters(
            {"doc_titles": ["Report A"], "region": ["Asia and the Pacific"]}, pg
        )
        assert result["doc_id"] == ["d2", "d3"]

    def test_titles_and_region_when_disjoint_then_sentinel(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d1"]
        pg.fetch_doc_ids_by_region.return_value = ["d9"]
        result = resolve_doc_level_filters(
            {"doc_titles": ["Report A"], "region": ["Asia and the Pacific"]}, pg
        )
        assert result["doc_id"] == [NO_MATCH_DOC_ID]
