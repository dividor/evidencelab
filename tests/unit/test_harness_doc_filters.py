"""Unit tests for the eval-harness document-level filter resolver.

The evaluation harness lets a test case use any of the data source's
config-declared filter fields. Fields whose values live on documents rather
than chunks — ``doc_titles`` (exact UI titles), ``region``, ``language`` and
the config-declared ``src_*`` fields — must be resolved to a ``doc_id`` filter
at run time because the harness calls chunk search directly (bypassing the
``/search`` route's own resolvers). These tests cover that resolution, its
AND-intersection with a pre-existing ``doc_id`` filter, the OR-union of values
within a field, and the no-match sentinel behaviour.
"""

from unittest.mock import MagicMock

import pytest

import ui.backend.utils.filter_helpers as filter_helpers
from ui.backend.utils.filter_helpers import NO_MATCH_DOC_ID, resolve_doc_level_filters

pytestmark = pytest.mark.unit

SOURCE = "test-source"


@pytest.fixture(autouse=True)
def _no_src_fields(monkeypatch):
    """Default the data source's ``src_field_mapping`` to empty for every test.

    Tests exercising ``src_*`` resolution override this with a real mapping.
    """
    monkeypatch.setattr(filter_helpers, "get_src_field_mapping", lambda source: {})


def _pg_titles(doc_ids):
    pg = MagicMock()
    pg.fetch_doc_ids_by_exact_titles.return_value = list(doc_ids)
    return pg


class TestResolveDocTitles:
    def test_no_doc_level_keys_when_absent_then_filters_returned_unchanged(self):
        filters = {"published_year_max": 2020, "country": "Kenya"}
        pg = MagicMock()
        assert resolve_doc_level_filters(filters, pg, SOURCE) == {
            "published_year_max": 2020,
            "country": "Kenya",
        }
        pg.fetch_doc_ids_by_exact_titles.assert_not_called()
        pg.fetch_doc_ids_by_region.assert_not_called()

    def test_single_title_when_set_then_replaced_by_doc_id_filter(self):
        filters = {"doc_titles": ["Report A"]}
        pg = _pg_titles(["d1"])
        result = resolve_doc_level_filters(filters, pg, SOURCE)
        assert "doc_titles" not in result
        assert result["doc_id"] == ["d1"]
        pg.fetch_doc_ids_by_exact_titles.assert_called_once_with(["Report A"])

    def test_multiple_titles_when_set_then_all_doc_ids_returned(self):
        filters = {"doc_titles": ["Report A", "Report B"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d2", "d1"]), SOURCE)
        assert result["doc_id"] == ["d1", "d2"]  # sorted, deterministic

    def test_comma_string_when_given_then_split_into_titles(self):
        filters = {"doc_titles": "Report A, Report B"}
        pg = _pg_titles(["d1"])
        resolve_doc_level_filters(filters, pg, SOURCE)
        pg.fetch_doc_ids_by_exact_titles.assert_called_once_with(
            ["Report A", "Report B"]
        )

    def test_blank_titles_when_only_whitespace_then_no_lookup_and_no_doc_id(self):
        filters = {"doc_titles": ["  ", ""]}
        pg = MagicMock()
        result = resolve_doc_level_filters(filters, pg, SOURCE)
        assert "doc_titles" not in result
        assert "doc_id" not in result
        pg.fetch_doc_ids_by_exact_titles.assert_not_called()

    def test_titles_when_no_docs_match_then_sentinel_doc_id(self):
        filters = {"doc_titles": ["Nonexistent"]}
        result = resolve_doc_level_filters(filters, _pg_titles([]), SOURCE)
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_existing_doc_id_when_titles_set_then_intersected(self):
        filters = {"doc_titles": ["Report A"], "doc_id": "d1,d2,d3"}
        result = resolve_doc_level_filters(
            filters, _pg_titles(["d2", "d3", "d4"]), SOURCE
        )
        assert result["doc_id"] == ["d2", "d3"]

    def test_existing_doc_id_when_disjoint_then_sentinel(self):
        filters = {"doc_titles": ["Report A"], "doc_id": ["d1"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d9"]), SOURCE)
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_invalid_titles_when_not_list_or_string_then_value_error(self):
        with pytest.raises(ValueError, match="doc_titles must be a list"):
            resolve_doc_level_filters({"doc_titles": 123}, MagicMock(), SOURCE)

    def test_input_dict_when_resolved_then_not_mutated(self):
        filters = {"doc_titles": ["Report A"], "country": "Kenya"}
        resolve_doc_level_filters(filters, _pg_titles(["d1"]), SOURCE)
        assert filters == {"doc_titles": ["Report A"], "country": "Kenya"}

    def test_non_dict_when_passed_then_returned_unchanged(self):
        assert resolve_doc_level_filters(None, MagicMock(), SOURCE) is None

    def test_country_when_set_then_left_untouched(self):
        # country is stamped on chunks and applied natively — never resolved here.
        filters = {"country": ["Kenya"], "doc_titles": ["Report A"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d1"]), SOURCE)
        assert result["country"] == ["Kenya"]
        assert result["doc_id"] == ["d1"]


class TestResolveRegion:
    def test_single_region_when_set_then_resolved_to_doc_ids(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1", "d2"]
        result = resolve_doc_level_filters(
            {"region": "Asia and the Pacific"}, pg, SOURCE
        )
        assert "region" not in result
        assert result["doc_id"] == ["d1", "d2"]
        pg.fetch_doc_ids_by_region.assert_called_once_with("Asia and the Pacific")

    def test_region_list_when_set_then_doc_ids_are_unioned(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.side_effect = [["d1", "d2"], ["d2", "d3"]]
        result = resolve_doc_level_filters(
            {"region": ["Asia and the Pacific", "Eastern Africa"]}, pg, SOURCE
        )
        assert result["doc_id"] == ["d1", "d2", "d3"]  # union, sorted
        assert pg.fetch_doc_ids_by_region.call_count == 2

    def test_region_name_with_comma_when_string_then_not_split(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1"]
        resolve_doc_level_filters(
            {"region": "Middle East, Northern Africa, and Eastern Europe"}, pg, SOURCE
        )
        pg.fetch_doc_ids_by_region.assert_called_once_with(
            "Middle East, Northern Africa, and Eastern Europe"
        )

    def test_region_when_no_docs_match_then_sentinel_doc_id(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = []
        result = resolve_doc_level_filters({"region": ["Nowhere"]}, pg, SOURCE)
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_invalid_region_when_not_list_or_string_then_value_error(self):
        with pytest.raises(ValueError, match="region must be a string or a list"):
            resolve_doc_level_filters({"region": 5}, MagicMock(), SOURCE)


class TestResolveLanguage:
    def test_language_names_when_set_then_normalised_to_codes(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = ["d1", "d2"]
        result = resolve_doc_level_filters(
            {"language": ["English", "French"]}, pg, SOURCE
        )
        assert "language" not in result
        assert result["doc_id"] == ["d1", "d2"]
        pg.fetch_doc_ids_by_language.assert_called_once_with(["en", "fr"])

    def test_language_codes_when_given_then_passed_through(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = ["d1"]
        resolve_doc_level_filters({"language": "en,fr"}, pg, SOURCE)
        pg.fetch_doc_ids_by_language.assert_called_once_with(["en", "fr"])

    def test_language_when_no_docs_match_then_sentinel_doc_id(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_language.return_value = []
        result = resolve_doc_level_filters({"language": ["English"]}, pg, SOURCE)
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_blank_language_when_only_whitespace_then_no_lookup(self):
        pg = MagicMock()
        result = resolve_doc_level_filters({"language": ["  "]}, pg, SOURCE)
        assert "language" not in result
        assert "doc_id" not in result
        pg.fetch_doc_ids_by_language.assert_not_called()

    def test_invalid_language_when_not_list_or_string_then_value_error(self):
        with pytest.raises(ValueError, match="language must be a string or a list"):
            resolve_doc_level_filters({"language": 7}, MagicMock(), SOURCE)


class TestResolveSrcFields:
    @pytest.fixture
    def _src_mapping(self, monkeypatch):
        monkeypatch.setattr(
            filter_helpers,
            "get_src_field_mapping",
            lambda source: {"src_evaluation_category": "Evaluation category"},
        )

    def test_src_field_when_set_then_resolved_via_jsonb_lookup(
        self, _src_mapping, monkeypatch
    ):
        calls = []

        def fake_jsonb(pg, raw_key, values):
            calls.append((raw_key, values))
            return ["d1", "d2"]

        monkeypatch.setattr(filter_helpers, "doc_ids_from_pg_jsonb", fake_jsonb)
        result = resolve_doc_level_filters(
            {"src_evaluation_category": ["Centralized"]}, MagicMock(), SOURCE
        )
        assert "src_evaluation_category" not in result
        assert result["doc_id"] == ["d1", "d2"]
        assert calls == [("Evaluation category", ["Centralized"])]

    def test_src_field_when_comma_string_then_split_into_values(
        self, _src_mapping, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            filter_helpers,
            "doc_ids_from_pg_jsonb",
            lambda pg, raw_key, values: calls.append(values) or ["d1"],
        )
        resolve_doc_level_filters(
            {"src_evaluation_category": "Centralized, Decentralized"},
            MagicMock(),
            SOURCE,
        )
        assert calls == [["Centralized", "Decentralized"]]

    def test_src_field_when_no_docs_match_then_sentinel_doc_id(
        self, _src_mapping, monkeypatch
    ):
        monkeypatch.setattr(
            filter_helpers, "doc_ids_from_pg_jsonb", lambda pg, raw_key, values: []
        )
        result = resolve_doc_level_filters(
            {"src_evaluation_category": ["Centralized"]}, MagicMock(), SOURCE
        )
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_src_field_when_not_in_mapping_then_left_untouched(self):
        # Only config-declared src_* fields resolve; unknown keys pass through.
        filters = {"src_unknown": ["x"], "doc_titles": ["Report A"]}
        result = resolve_doc_level_filters(filters, _pg_titles(["d1"]), SOURCE)
        assert result["src_unknown"] == ["x"]
        assert result["doc_id"] == ["d1"]

    def test_invalid_src_value_when_not_list_or_string_then_value_error(
        self, _src_mapping
    ):
        with pytest.raises(
            ValueError, match="src_evaluation_category must be a string or a list"
        ):
            resolve_doc_level_filters(
                {"src_evaluation_category": 3}, MagicMock(), SOURCE
            )


class TestResolveCombined:
    def test_titles_and_region_when_both_set_then_intersected(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d1", "d2", "d3"]
        pg.fetch_doc_ids_by_region.return_value = ["d2", "d3", "d4"]
        result = resolve_doc_level_filters(
            {"doc_titles": ["Report A"], "region": ["Asia and the Pacific"]},
            pg,
            SOURCE,
        )
        assert result["doc_id"] == ["d2", "d3"]

    def test_titles_and_region_when_disjoint_then_sentinel(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_exact_titles.return_value = ["d1"]
        pg.fetch_doc_ids_by_region.return_value = ["d9"]
        result = resolve_doc_level_filters(
            {"doc_titles": ["Report A"], "region": ["Asia and the Pacific"]},
            pg,
            SOURCE,
        )
        assert result["doc_id"] == [NO_MATCH_DOC_ID]

    def test_language_and_region_when_both_set_then_intersected(self):
        pg = MagicMock()
        pg.fetch_doc_ids_by_region.return_value = ["d1", "d2"]
        pg.fetch_doc_ids_by_language.return_value = ["d2", "d3"]
        result = resolve_doc_level_filters(
            {"region": ["Asia and the Pacific"], "language": ["English"]}, pg, SOURCE
        )
        assert result["doc_id"] == ["d2"]
