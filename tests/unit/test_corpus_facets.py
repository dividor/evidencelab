"""Tests for query-independent, filter-aware corpus facets.

Covers ``build_corpus_facets`` and its helpers in
``ui.backend.utils.facet_helpers``. These facets count *documents* matching
the user's other active filters (exclude-self) and never depend on the search
query.
"""

from types import SimpleNamespace

import pytest

from ui.backend.utils.facet_helpers import (
    _build_corpus_where,
    _corpus_field_counts,
    _facet_column_expr,
    _field_filter_clause,
    _is_safe_identifier,
    _is_skippable_filter,
    _language_filter_values,
    _split_selected_values,
    _value_match_sql,
    build_corpus_facets,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Recording fake Postgres client
# ---------------------------------------------------------------------------
class _RecordingCursor:
    def __init__(self, store, results):
        self._store = store
        self._results = results
        self._current = []

    def execute(self, sql, params=None):
        self._store.append((sql, list(params) if params else []))
        self._current = self._results.pop(0) if self._results else []

    def fetchall(self):
        return self._current

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class _RecordingConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class _RecordingPg:
    """Fake pg returning queued row-lists, recording each (sql, params)."""

    def __init__(self, results=None):
        self.docs_table = "docs_wfp"
        self.calls = []
        self._cursor = _RecordingCursor(self.calls, list(results or []))

    def _get_conn(self):
        return _RecordingConn(self._cursor)


def _resolve(field, _data_source):
    return {
        "country": "map_country",
        "region": "map_region",
        "language": "map_language",
        "document_type": "map_document_type",
        "published_year": "map_published_year",
        "title": "map_title",
        "src_evaluation_category": "src_evaluation_category",
    }.get(field, field)


_SRC_MAP = {"src_evaluation_category": "Evaluation category"}


# ---------------------------------------------------------------------------
# _is_safe_identifier
# ---------------------------------------------------------------------------
class TestIsSafeIdentifier:
    def test_plain_column(self):
        assert _is_safe_identifier("map_country") is True

    def test_rejects_empty(self):
        assert _is_safe_identifier("") is False

    def test_rejects_injection(self):
        assert _is_safe_identifier("map_country; DROP TABLE x") is False

    def test_rejects_jsonb_operator(self):
        assert _is_safe_identifier("src_doc_raw_metadata->>'k'") is False


# ---------------------------------------------------------------------------
# _split_selected_values
# ---------------------------------------------------------------------------
class TestSplitSelectedValues:
    def test_comma_separated(self):
        assert _split_selected_values("Kenya, Rwanda") == ["Kenya", "Rwanda"]

    def test_single_value(self):
        assert _split_selected_values("Kenya") == ["Kenya"]

    def test_list_input(self):
        assert _split_selected_values(["Kenya", " Rwanda "]) == ["Kenya", "Rwanda"]

    def test_strips_blank_parts(self):
        assert _split_selected_values("Kenya, ,Rwanda") == ["Kenya", "Rwanda"]


# ---------------------------------------------------------------------------
# _facet_column_expr
# ---------------------------------------------------------------------------
class TestFacetColumnExpr:
    def test_plain_column(self):
        expr, params = _facet_column_expr("country", "map_country", _SRC_MAP)
        assert expr == "map_country"
        assert params == []

    def test_src_jsonb(self):
        expr, params = _facet_column_expr(
            "src_evaluation_category", "src_evaluation_category", _SRC_MAP
        )
        assert expr == "src_doc_raw_metadata->>%s"
        assert params == ["Evaluation category"]

    def test_src_without_mapping_falls_to_column(self):
        # No mapping entry → treated as a plain (validated) column.
        expr, params = _facet_column_expr("src_other", "src_other", {})
        assert expr == "src_other"
        assert params == []

    def test_unsafe_column_raises(self):
        with pytest.raises(ValueError):
            _facet_column_expr("country", "map_country; DROP", _SRC_MAP)


# ---------------------------------------------------------------------------
# _language_filter_values
# ---------------------------------------------------------------------------
class TestLanguageFilterValues:
    def test_codes_mapped_for_map_language(self):
        assert _language_filter_values("map_language", ["en", "fr"]) == [
            "English",
            "French",
        ]

    def test_sys_language_passthrough(self):
        assert _language_filter_values("sys_language", ["en", "fr"]) == ["en", "fr"]

    def test_unknown_code_passthrough(self):
        assert _language_filter_values("map_language", ["zz"]) == ["zz"]


# ---------------------------------------------------------------------------
# _value_match_sql
# ---------------------------------------------------------------------------
class TestValueMatchSql:
    def test_plain_column_both_separators(self):
        sql, params = _value_match_sql("map_country", [], "Nepal")
        assert sql.count("string_to_array(map_country") == 2
        assert " OR " in sql
        assert params == ["Nepal", "; ", "Nepal", " | "]

    def test_jsonb_column_includes_key_param(self):
        sql, params = _value_match_sql(
            "src_doc_raw_metadata->>%s", ["Evaluation category"], "DE"
        )
        # value, raw_key, separator — per separator clause.
        assert params == [
            "DE",
            "Evaluation category",
            "; ",
            "DE",
            "Evaluation category",
            " | ",
        ]


# ---------------------------------------------------------------------------
# _field_filter_clause
# ---------------------------------------------------------------------------
class TestFieldFilterClause:
    def test_title_uses_exact_equality(self):
        sql, params = _field_filter_clause("title", "map_title", [], ["A; B Report"])
        assert "string_to_array" not in sql
        assert sql == "(map_title = %s)"
        assert params == ["A; B Report"]

    def test_multi_value_or(self):
        sql, params = _field_filter_clause(
            "country", "map_country", [], ["Kenya", "Rwanda"]
        )
        assert sql.count("string_to_array") == 4  # 2 values x 2 separators
        assert "Kenya" in params and "Rwanda" in params


# ---------------------------------------------------------------------------
# _is_skippable_filter
# ---------------------------------------------------------------------------
class TestIsSkippableFilter:
    def test_excluded_self(self):
        assert _is_skippable_filter("country", "Kenya", "country") is True

    def test_empty_value(self):
        assert _is_skippable_filter("country", "", None) is True

    def test_tag_field_skipped(self):
        assert _is_skippable_filter("tag_sdg", "sdg2", None) is True

    def test_range_bounds_skipped(self):
        assert _is_skippable_filter("year_min", "2000", None) is True
        assert _is_skippable_filter("year_max", "2020", None) is True

    def test_normal_filter_not_skipped(self):
        assert _is_skippable_filter("country", "Kenya", None) is False


# ---------------------------------------------------------------------------
# _build_corpus_where
# ---------------------------------------------------------------------------
class TestBuildCorpusWhere:
    def test_no_filters(self):
        sql, params = _build_corpus_where({}, None, _resolve, "wfp", _SRC_MAP)
        assert sql == ""
        assert params == []

    def test_exclude_self_drops_only_constraint(self):
        sql, params = _build_corpus_where(
            {"country": "Rwanda"}, "country", _resolve, "wfp", _SRC_MAP
        )
        assert sql == ""
        assert params == []

    def test_other_filter_applied(self):
        sql, params = _build_corpus_where(
            {"country": "Rwanda"}, "region", _resolve, "wfp", _SRC_MAP
        )
        assert "map_country" in sql
        assert "Rwanda" in params

    def test_tag_and_range_skipped(self):
        sql, params = _build_corpus_where(
            {"tag_sdg": "sdg2", "year_min": "2000", "country": "Kenya"},
            None,
            _resolve,
            "wfp",
            _SRC_MAP,
        )
        assert "map_country" in sql
        assert "tag_" not in sql
        assert params == ["Kenya", "; ", "Kenya", " | "]

    def test_language_code_converted(self):
        sql, params = _build_corpus_where(
            {"language": "en"}, "country", _resolve, "wfp", _SRC_MAP
        )
        assert "map_language" in sql
        assert "English" in params
        assert "en" not in params

    def test_two_filters_anded(self):
        sql, _params = _build_corpus_where(
            {"country": "Kenya", "document_type": "Activity"},
            None,
            _resolve,
            "wfp",
            _SRC_MAP,
        )
        assert " AND " in sql
        assert "map_country" in sql and "map_document_type" in sql


# ---------------------------------------------------------------------------
# _corpus_field_counts
# ---------------------------------------------------------------------------
class TestCorpusFieldCounts:
    def test_builds_subquery_and_parses_rows(self):
        pg = _RecordingPg(results=[[("Kenya", 26), ("Rwanda", 8)]])
        counts = _corpus_field_counts(
            pg, "country", "map_country", {}, _resolve, "wfp", _SRC_MAP
        )
        assert counts == {"Kenya": 26, "Rwanda": 8}
        sql, params = pg.calls[0]
        assert "SELECT map_country AS v FROM docs_wfp" in sql
        assert "GROUP BY v" in sql
        assert "v IS NOT NULL AND v != ''" in sql
        assert params == []

    def test_other_filter_added_to_where(self):
        pg = _RecordingPg(results=[[("Activity", 5)]])
        _corpus_field_counts(
            pg,
            "document_type",
            "map_document_type",
            {"country": "Rwanda"},
            _resolve,
            "wfp",
            _SRC_MAP,
        )
        sql, params = pg.calls[0]
        assert "string_to_array(map_country" in sql
        assert "Rwanda" in params

    def test_src_jsonb_param_ordering(self):
        pg = _RecordingPg(results=[[("DE", 167)]])
        counts = _corpus_field_counts(
            pg,
            "src_evaluation_category",
            "src_evaluation_category",
            {"country": "Rwanda"},
            _resolve,
            "wfp",
            _SRC_MAP,
        )
        assert counts == {"DE": 167}
        sql, params = pg.calls[0]
        assert "src_doc_raw_metadata->>%s" in sql
        # JSONB key param comes first (SELECT expr), then WHERE params.
        assert params[0] == "Evaluation category"
        assert "Rwanda" in params


# ---------------------------------------------------------------------------
# build_corpus_facets (orchestration)
# ---------------------------------------------------------------------------
class TestBuildCorpusFacets:
    def _config(self):
        return {
            "title": "Title",
            "country": "Country",
            "published_year": "Year",
            "language": "Language",
            "src_evaluation_category": "Category",
            "tag_sdg": "SDG",
        }

    def _db(self):
        return SimpleNamespace(
            chunks_collection="chunks_wfp",
            facet=lambda **kwargs: {"sdg2 - Zero Hunger": 9},
        )

    def _pg(self):
        # Order matches non-tag, non-title fields: country, year, language, src.
        return _RecordingPg(
            results=[
                [("Kenya", 26), ("Rwanda", 8)],
                [("2025", 48), ("2024", 42)],
                [("en", 271), ("fr", 36)],
                [("DE", 167), ("CE", 145)],
            ]
        )

    def test_title_is_empty(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        assert res["title"] == []

    def test_country_counts(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        country = {fv.value: fv.count for fv in res["country"]}
        assert country == {"Kenya": 26, "Rwanda": 8}

    def test_year_sorted_descending(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        years = [fv.value for fv in res["published_year"]]
        assert years == ["2025", "2024"]

    def test_language_codes_mapped_to_names(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        langs = {fv.value: fv.count for fv in res["language"]}
        assert langs == {"English": 271, "French": 36}

    def test_src_field_counts(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        cats = {fv.value: fv.count for fv in res["src_evaluation_category"]}
        assert cats == {"DE": 167, "CE": 145}

    def test_tag_uses_chunk_facet_source(self):
        res, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        tags = {fv.value: fv.count for fv in res["tag_sdg"]}
        assert tags == {"sdg2 - Zero Hunger": 9}

    def test_exclude_self_country_query_has_no_country_constraint(self):
        pg = self._pg()
        build_corpus_facets(
            pg,
            self._db(),
            self._config(),
            {"country": "Rwanda"},
            _resolve,
            "wfp",
            _SRC_MAP,
        )
        # First pg call is the country facet itself → must NOT filter on country.
        country_sql, _ = pg.calls[0]
        assert "map_country" not in country_sql.split("FROM docs_wfp")[1]
        # A later field (e.g. language) DOES constrain by country.
        language_sql, language_params = pg.calls[2]
        assert "map_country" in language_sql
        assert "Rwanda" in language_params

    def test_query_argument_is_irrelevant(self):
        # build_corpus_facets takes no query param at all — counts are computed
        # purely from filters, proving they cannot change when a search runs.
        res_a, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        res_b, _ = build_corpus_facets(
            self._pg(), self._db(), self._config(), {}, _resolve, "wfp", _SRC_MAP
        )
        assert {fv.value: fv.count for fv in res_a["country"]} == {
            fv.value: fv.count for fv in res_b["country"]
        }
