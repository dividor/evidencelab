"""Tests for ui.backend.utils.facet_helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ui.backend.utils.facet_helpers import (
    FILTER_FIELD_MAX_UNIQUE_VALS,
    _all_values_numerical,
    _build_range_info,
    _facet_storage_field,
    _facet_tag_field,
    _get_raw_counts,
    _is_dynamic_field,
    _safe_facet_query,
    _validate_and_route_field,
    build_facets_from_db,
    build_generic_facets,
    build_year_facets,
)


# ---------------------------------------------------------------------------
# _all_values_numerical
# ---------------------------------------------------------------------------
class TestAllValuesNumerical:
    def test_pure_integers(self):
        assert _all_values_numerical({"1": 5, "2": 3, "100": 1}) is True

    def test_pure_floats(self):
        assert _all_values_numerical({"1.5": 2, "3.14": 1}) is True

    def test_mixed_int_and_float(self):
        assert _all_values_numerical({"1": 4, "2.5": 3}) is True

    def test_non_numerical_string(self):
        assert _all_values_numerical({"abc": 5, "2": 3}) is False

    def test_mixed_with_text(self):
        assert _all_values_numerical({"100": 10, "high": 2}) is False

    def test_empty_dict(self):
        # No non-empty keys → has_values stays False
        assert _all_values_numerical({}) is False

    def test_only_none_and_empty(self):
        assert _all_values_numerical({None: 3, "": 2}) is False

    def test_none_and_empty_skipped(self):
        # None and "" are skipped; remaining keys are numerical
        assert _all_values_numerical({None: 1, "": 2, "42": 5}) is True

    def test_negative_numbers(self):
        assert _all_values_numerical({"-1": 3, "-0.5": 2, "10": 1}) is True


# ---------------------------------------------------------------------------
# _build_range_info
# ---------------------------------------------------------------------------
class TestBuildRangeInfo:
    def test_integer_keys(self):
        info = _build_range_info({"10": 5, "20": 3, "5": 1})
        assert info.min == 5.0
        assert info.max == 20.0

    def test_float_keys(self):
        info = _build_range_info({"1.5": 2, "3.14": 1, "0.1": 4})
        assert info.min == pytest.approx(0.1)
        assert info.max == pytest.approx(3.14)

    def test_skips_none_and_empty(self):
        info = _build_range_info({None: 1, "": 2, "10": 5, "50": 3})
        assert info.min == 10.0
        assert info.max == 50.0

    def test_single_value(self):
        info = _build_range_info({"42": 1})
        assert info.min == 42.0
        assert info.max == 42.0


# ---------------------------------------------------------------------------
# _is_dynamic_field
# ---------------------------------------------------------------------------
class TestIsDynamicField:
    def test_src_prefix(self):
        assert _is_dynamic_field("src_budget") is True

    def test_tag_prefix(self):
        assert _is_dynamic_field("tag_sdg") is True

    def test_core_field(self):
        assert _is_dynamic_field("organization") is False
        assert _is_dynamic_field("country") is False

    def test_map_prefix(self):
        assert _is_dynamic_field("map_country") is False


# ---------------------------------------------------------------------------
# _validate_and_route_field
# ---------------------------------------------------------------------------
class TestValidateAndRouteField:
    def test_numerical_dynamic_field_goes_to_range(self):
        facets = {}
        range_fields = {}
        _validate_and_route_field(
            "src_budget",
            {"100": 5, "200": 3, "500": 1},
            facets,
            range_fields,
        )
        assert "src_budget" not in facets
        assert "src_budget" in range_fields
        assert range_fields["src_budget"].min == 100.0
        assert range_fields["src_budget"].max == 500.0

    def test_nonnumerical_dynamic_field_goes_to_facets(self):
        facets = {}
        range_fields = {}
        _validate_and_route_field(
            "src_region",
            {"Africa": 10, "Asia": 8},
            facets,
            range_fields,
        )
        assert "src_region" in facets
        assert "src_region" not in range_fields
        assert len(facets["src_region"]) == 2

    def test_nonnumerical_exceeding_limit_raises(self):
        raw_counts = {f"val_{i}": 1 for i in range(FILTER_FIELD_MAX_UNIQUE_VALS + 1)}
        facets = {}
        range_fields = {}
        with pytest.raises(ValueError, match="unique values"):
            _validate_and_route_field("src_too_many", raw_counts, facets, range_fields)

    def test_nonnumerical_at_limit_does_not_raise(self):
        raw_counts = {f"val_{i}": 1 for i in range(FILTER_FIELD_MAX_UNIQUE_VALS)}
        facets = {}
        range_fields = {}
        _validate_and_route_field("src_ok", raw_counts, facets, range_fields)
        assert "src_ok" in facets

    def test_numerical_exceeding_limit_goes_to_range(self):
        """Numerical fields are not subject to the cardinality limit."""
        raw_counts = {str(i): 1 for i in range(FILTER_FIELD_MAX_UNIQUE_VALS + 50)}
        facets = {}
        range_fields = {}
        _validate_and_route_field("src_big_num", raw_counts, facets, range_fields)
        assert "src_big_num" not in facets
        assert "src_big_num" in range_fields

    def test_core_field_not_validated(self):
        """Core fields (non src_/tag_) skip cardinality validation."""
        raw_counts = {f"val_{i}": 1 for i in range(2000)}
        facets = {}
        range_fields = {}
        # Should NOT raise even though > 1000 unique values
        _validate_and_route_field("country", raw_counts, facets, range_fields)
        assert "country" in facets

    def test_empty_numerical_field_gives_empty_facets(self):
        facets = {}
        range_fields = {}
        _validate_and_route_field("src_score", {None: 3, "": 2}, facets, range_fields)
        # All keys are empty — _all_values_numerical returns False
        # So it falls through to facets as empty list
        assert facets.get("src_score") == []

    def test_tag_field_numerical(self):
        facets = {}
        range_fields = {}
        _validate_and_route_field(
            "tag_confidence",
            {"0.9": 10, "0.8": 5, "0.7": 3},
            facets,
            range_fields,
        )
        assert "tag_confidence" in range_fields
        assert range_fields["tag_confidence"].min == pytest.approx(0.7)
        assert range_fields["tag_confidence"].max == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# build_year_facets
# ---------------------------------------------------------------------------
class TestBuildYearFacets:
    def test_sorted_descending(self):
        result = build_year_facets({"2020": 5, "2023": 3, "2021": 10})
        values = [fv.value for fv in result]
        assert values == ["2023", "2021", "2020"]

    def test_skips_none_and_empty(self):
        result = build_year_facets({None: 1, "": 2, "2022": 5})
        assert len(result) == 1
        assert result[0].value == "2022"


# ---------------------------------------------------------------------------
# build_generic_facets
# ---------------------------------------------------------------------------
class TestBuildGenericFacets:
    def test_sorted_by_count(self):
        result = build_generic_facets({"A": 1, "B": 10, "C": 5})
        values = [fv.value for fv in result]
        assert values == ["B", "C", "A"]

    def test_splits_semicolon(self):
        result = build_generic_facets({"X; Y": 3, "X": 2})
        # X should have 3 + 2 = 5, Y should have 3
        result_dict = {fv.value: fv.count for fv in result}
        assert result_dict["X"] == 5
        assert result_dict["Y"] == 3


# ---------------------------------------------------------------------------
# _safe_facet_query
# ---------------------------------------------------------------------------
class TestSafeFacetQuery:
    def test_returns_result_on_success(self):
        result = _safe_facet_query(lambda: {"Global": 10}, "test_field")
        assert result == {"Global": 10}

    def test_returns_none_on_exception(self):
        def failing():
            raise RuntimeError("No index")

        result = _safe_facet_query(failing, "test_field")
        assert result is None

    def test_returns_empty_dict_from_fn(self):
        result = _safe_facet_query(lambda: {}, "test_field")
        assert result == {}


# ---------------------------------------------------------------------------
# _facet_tag_field
# ---------------------------------------------------------------------------
class TestFacetTagField:
    def test_queries_chunks_collection(self):
        db = MagicMock()
        db.chunks_collection = "chunks_uneg"
        db.facet.return_value = {"sdg1": 10, "sdg2": 5}

        result = _facet_tag_field(db, "tag_sdg")

        assert result == {"sdg1": 10, "sdg2": 5}
        db.facet.assert_called_once_with(
            collection_name="chunks_uneg",
            key="tag_sdg",
            filter_conditions=None,
            limit=2000,
            exact=False,
        )

    def test_returns_empty_when_no_facet_method(self):
        db = SimpleNamespace()  # no facet attribute
        result = _facet_tag_field(db, "tag_sdg")
        assert result == {}


# ---------------------------------------------------------------------------
# _facet_storage_field
# ---------------------------------------------------------------------------
class TestFacetStorageField:
    def test_routes_sys_field_to_postgres(self):
        db = MagicMock()
        pg = MagicMock()
        pg._get_conn.return_value.__enter__ = MagicMock()
        pg._get_conn.return_value.__exit__ = MagicMock()

        _facet_storage_field(db, pg, "language", "sys_language", None)
        # Should NOT call db.facet_documents
        db.facet_documents.assert_not_called()

    def test_routes_non_sys_field_to_qdrant(self):
        db = MagicMock()
        db.facet_documents.return_value = {"Global": 10}

        result = _facet_storage_field(
            db, None, "src_geographic_scope", "src_geographic_scope", None
        )

        assert result == {"Global": 10}
        db.facet_documents.assert_called_once_with(
            key="src_geographic_scope",
            filter_conditions=None,
            limit=2000,
            exact=False,
        )

    def test_sys_field_falls_to_qdrant_when_no_pg(self):
        db = MagicMock()
        db.facet_documents.return_value = {"en": 100}

        result = _facet_storage_field(db, None, "language", "sys_language", None)

        assert result == {"en": 100}
        db.facet_documents.assert_called_once()


# ---------------------------------------------------------------------------
# _get_raw_counts
# ---------------------------------------------------------------------------
class TestGetRawCounts:
    def test_tag_field_routes_to_chunks(self):
        db = MagicMock()
        db.chunks_collection = "chunks_uneg"
        db.facet.return_value = {"sdg1": 10}

        result = _get_raw_counts(db, None, "tag_sdg", None, lambda f, s: f)

        assert result == {"sdg1": 10}
        db.facet.assert_called_once()
        db.facet_documents.assert_not_called()

    def test_src_field_routes_to_documents(self):
        db = MagicMock()
        db.data_source = "uneg"
        db.facet_documents.return_value = {"Global": 10, "Country": 50}

        result = _get_raw_counts(db, None, "src_geographic_scope", None, lambda f, s: f)

        assert result == {"Global": 10, "Country": 50}
        db.facet_documents.assert_called_once()

    def test_core_field_routes_to_documents(self):
        db = MagicMock()
        db.data_source = "uneg"
        db.facet_documents.return_value = {"UNDP": 100}

        result = _get_raw_counts(
            db, None, "organization", None, lambda f, s: "map_organization"
        )

        assert result == {"UNDP": 100}

    def test_returns_none_on_qdrant_error(self):
        db = MagicMock()
        db.data_source = "uneg"
        db.facet_documents.side_effect = RuntimeError("No index")

        result = _get_raw_counts(db, None, "src_geographic_scope", None, lambda f, s: f)

        assert result is None

    def test_returns_none_on_tag_error(self):
        db = MagicMock()
        db.chunks_collection = "chunks_uneg"
        db.facet.side_effect = RuntimeError("No index")

        result = _get_raw_counts(db, None, "tag_sdg", None, lambda f, s: f)

        assert result is None


# ---------------------------------------------------------------------------
# build_facets_from_db
# ---------------------------------------------------------------------------
class TestBuildFacetsFromDb:
    @staticmethod
    def _mock_db(facet_docs=None, facet_chunks=None):
        db = MagicMock()
        db.data_source = "uneg"
        db.documents_collection = "documents_uneg"
        db.chunks_collection = "chunks_uneg"
        db.facet_documents.return_value = facet_docs or {}
        db.facet.return_value = facet_chunks or {}
        return db

    def test_title_field_always_empty(self):
        db = self._mock_db()
        config = {"title": "Document Title", "organization": "Organization"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert facets["title"] == []
        assert "title" not in ranges

    def test_src_field_returns_facets(self):
        db = self._mock_db(facet_docs={"Global": 10, "Country": 50})
        config = {"src_geographic_scope": "Geographic Scope"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert "src_geographic_scope" in facets
        values = {fv.value: fv.count for fv in facets["src_geographic_scope"]}
        assert values["Country"] == 50
        assert values["Global"] == 10

    def test_tag_field_returns_facets(self):
        db = self._mock_db(facet_chunks={"sdg1": 20, "sdg2": 10})
        config = {"tag_sdg": "SDG"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert "tag_sdg" in facets
        assert len(facets["tag_sdg"]) == 2

    def test_failed_field_returns_empty_list(self):
        db = self._mock_db()
        db.facet_documents.side_effect = RuntimeError("No index")
        config = {"src_missing": "Missing Field"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert facets["src_missing"] == []

    def test_failed_tag_field_returns_empty_list(self):
        db = self._mock_db()
        db.facet.side_effect = RuntimeError("No index")
        config = {"tag_missing": "Missing Tag"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert facets["tag_missing"] == []

    def test_published_year_uses_year_facets(self):
        db = self._mock_db(facet_docs={"2023": 10, "2020": 5, "2022": 8})
        config = {"published_year": "Year Published"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        years = [fv.value for fv in facets["published_year"]]
        assert years == ["2023", "2022", "2020"]  # descending

    def test_numerical_src_goes_to_range_fields(self):
        db = self._mock_db(facet_docs={"100": 5, "200": 3, "500": 1})
        config = {"src_budget": "Budget"}
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert "src_budget" not in facets
        assert "src_budget" in ranges
        assert ranges["src_budget"].min == 100.0
        assert ranges["src_budget"].max == 500.0

    def test_mixed_fields_all_processed(self):
        db = self._mock_db(
            facet_docs={"UNDP": 100, "FAO": 50},
            facet_chunks={"sdg1": 20},
        )
        config = {
            "title": "Title",
            "organization": "Organization",
            "tag_sdg": "SDG",
        }
        facets, ranges = build_facets_from_db(db, config, None, lambda f, s: f)
        assert "title" in facets
        assert "organization" in facets
        assert "tag_sdg" in facets
        assert len(facets) == 3
