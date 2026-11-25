"""Unit tests for the LLM-usage rollup route helpers.

Database execution is integration-flavoured; here we cover the pure
helpers that determine the response shape, the SQL builder string
contents, and the input-validation guards. The end-to-end accuracy of
the persisted numbers is already covered by
``test_token_usage_end_to_end.py``.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ui.backend.routes.llm_usage import (
    _ANONYMOUS_LABEL,
    _BUCKETS,
    _DEFAULT_RANGE_DAYS,
    _FOOTPRINT_COLUMNS,
    _GROUP_BYS,
    _NO_GROUP_LABEL,
    _SORT_KEYS,
    _VALID_ACTIVITY_TYPES,
    _build_group_grouped_sql,
    _build_user_grouped_sql,
    _resolve_date_range,
    _row_to_dict,
    _validate_activity_type,
    _validate_bucket,
    _validate_group_by,
    compute_totals,
    sort_rows,
)

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidators:
    @pytest.mark.parametrize("good", sorted(_BUCKETS))
    def test_bucket_whitelist_passes(self, good):
        assert _validate_bucket(good) == good

    def test_bucket_rejects_unknown(self):
        with pytest.raises(HTTPException) as exc:
            _validate_bucket("year")
        assert exc.value.status_code == 422

    def test_bucket_rejects_sql_injection_attempt(self):
        """The bucket is interpolated into SQL — must reject anything funny."""
        with pytest.raises(HTTPException):
            _validate_bucket("week; DROP TABLE users")

    @pytest.mark.parametrize("good", sorted(_GROUP_BYS))
    def test_group_by_whitelist_passes(self, good):
        assert _validate_group_by(good) == good

    def test_group_by_rejects_unknown(self):
        with pytest.raises(HTTPException) as exc:
            _validate_group_by("model")
        assert exc.value.status_code == 422

    @pytest.mark.parametrize("good", sorted(_VALID_ACTIVITY_TYPES))
    def test_activity_type_whitelist_passes(self, good):
        assert _validate_activity_type(good) == good

    def test_activity_type_none_or_empty_passes_through(self):
        assert _validate_activity_type(None) is None
        assert _validate_activity_type("") is None

    def test_activity_type_rejects_unknown(self):
        with pytest.raises(HTTPException) as exc:
            _validate_activity_type("rogue")
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Date range resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveDateRange:
    def test_defaults_to_last_30_days(self):
        start, end = _resolve_date_range(None, None)
        # End is exclusive (today + 1)
        delta = end - start
        assert delta.days == _DEFAULT_RANGE_DAYS + 1
        assert start.tzinfo is timezone.utc
        assert end.tzinfo is timezone.utc

    def test_explicit_range_is_honoured(self):
        start, end = _resolve_date_range(date(2026, 5, 1), date(2026, 5, 31))
        assert start == datetime(2026, 5, 1, tzinfo=timezone.utc)
        # End is exclusive — to_date + 1 day
        assert end == datetime(2026, 6, 1, tzinfo=timezone.utc)

    def test_inverted_range_rejected(self):
        with pytest.raises(HTTPException):
            _resolve_date_range(date(2026, 5, 31), date(2026, 5, 1))

    def test_partial_from_only(self):
        """Only ``from_date`` provided — ``to`` defaults to today."""
        start, end = _resolve_date_range(date(2020, 1, 1), None)
        assert start.year == 2020 and start.month == 1 and start.day == 1
        # End is today + 1; just check it's after start
        assert end > start


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSqlBuilders:
    """We don't execute the SQL here — we verify shape + parameter bindings."""

    def test_user_grouped_sql_uses_left_join_users(self):
        sql = _build_user_grouped_sql("week", None)
        assert "LEFT JOIN users u" in sql
        assert "date_trunc(:bucket" in sql
        assert ":from_dt" in sql and ":to_dt" in sql
        # Anonymous fallback present
        assert _ANONYMOUS_LABEL in sql

    def test_user_grouped_sql_omits_activity_filter_when_none(self):
        sql = _build_user_grouped_sql("week", None)
        assert ":activity_type" not in sql

    def test_user_grouped_sql_adds_activity_filter_when_provided(self):
        sql = _build_user_grouped_sql("week", "assistant-basic")
        # Filter must mirror the frontend semantics: filters.type, then
        # filters.mode, then 'search'. Plain search rows are stored with
        # no ``type`` key — a literal ``filters->>'type' = 'search'``
        # would return zero rows.
        assert (
            "COALESCE(ua.filters->>'type', ua.filters->>'mode', 'search')"
            " = :activity_type"
        ) in sql

    def test_search_filter_matches_rows_with_no_filter_type_set(self):
        """Regression: 'search' filter must include the COALESCE default.

        Plain search activity is logged with ``filters`` having no
        ``type`` key at all (only the assistant flow explicitly writes
        ``filters.type``). Without COALESCE, a SQL filter of
        ``filters->>'type' = 'search'`` would return zero rows.

        This test asserts the SQL string contains the COALESCE form, so
        it stays valid regardless of how many rows exist in the live DB.
        """
        sql = _build_user_grouped_sql("week", "search")
        assert "COALESCE(ua.filters->>'type'" in sql
        assert "'search'" in sql  # the COALESCE default sits inline
        # No leftover literal-equality form.
        assert "ua.filters->>'type' = :activity_type" not in sql

    def test_group_grouped_sql_uses_three_branches(self):
        """Joined members + anonymous + no-group user union."""
        sql = _build_group_grouped_sql("month", None)
        assert "JOIN user_group_members" in sql
        assert _ANONYMOUS_LABEL in sql
        assert _NO_GROUP_LABEL in sql
        # Three UNION ALL branches (one between each pair).
        assert sql.count("UNION ALL") == 2

    def test_bucket_is_interpolated_safely(self):
        """Bucket should appear in the date_trunc bind site, not be SQL-injected."""
        sql = _build_user_grouped_sql("day", None)
        assert "date_trunc(:bucket" in sql
        # The value isn't pasted in literally — it's bound at execute time.
        assert "'day'" not in sql


# ---------------------------------------------------------------------------
# _row_to_dict — shaping the result row
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRowToDict:
    def _row(self, **overrides):
        defaults = {
            "bucket_start": datetime(2026, 5, 26, tzinfo=timezone.utc),
            "group_key": "user@example.com",
            "group_label": "Test User",
            "request_count": 12,
            "prompt_tokens": 1234,
            "completion_tokens": 567,
            "total_tokens": 1801,
            "cost_usd": Decimal("0.001500"),
            **{column: None for column in _FOOTPRINT_COLUMNS},
            "footprint_unestimated_tokens": 0,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_basic_shape(self):
        out = _row_to_dict(self._row())
        assert out["bucket_start"] == "2026-05-26"
        assert out["group_label"] == "Test User"
        assert out["request_count"] == 12
        assert out["prompt_tokens"] == 1234
        assert out["completion_tokens"] == 567
        assert out["total_tokens"] == 1801
        assert out["cost_usd"] == "0.001500"
        assert all(out[c] is None for c in _FOOTPRINT_COLUMNS)
        assert out["footprint_unestimated_tokens"] == 0

    def test_date_input_renders_as_iso(self):
        """Postgres date_trunc may yield a date, not a datetime, in some setups."""
        out = _row_to_dict(self._row(bucket_start=date(2026, 6, 1)))
        assert out["bucket_start"] == "2026-06-01"

    def test_anonymous_row(self):
        out = _row_to_dict(
            self._row(group_key=_ANONYMOUS_LABEL, group_label=_ANONYMOUS_LABEL)
        )
        assert out["group_key"] == _ANONYMOUS_LABEL
        assert out["group_label"] == _ANONYMOUS_LABEL

    def test_zero_cost_keeps_six_decimal_format(self):
        out = _row_to_dict(self._row(cost_usd=Decimal("0")))
        assert out["cost_usd"] == "0.000000"


# ---------------------------------------------------------------------------
# compute_totals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeTotals:
    @staticmethod
    def _row(**overrides):
        defaults = {
            "bucket_start": "2026-05-26",
            "group_key": "a",
            "group_label": "A",
            "request_count": 1,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": "0.000000",
            **{column: None for column in _FOOTPRINT_COLUMNS},
            "footprint_unestimated_tokens": 0,
        }
        defaults.update(overrides)
        return defaults

    def test_empty_rows(self):
        t = compute_totals([])
        assert t["request_count"] == 0
        assert t["cost_usd"] == "0.000000"

    def test_sums_across_rows(self):
        rows = [
            self._row(
                request_count=2,
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd="0.001000",
            ),
            self._row(
                request_count=3,
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                cost_usd="0.002500",
            ),
        ]
        t = compute_totals(rows)
        assert t["request_count"] == 5
        assert t["prompt_tokens"] == 300
        assert t["completion_tokens"] == 150
        assert t["total_tokens"] == 450
        assert t["cost_usd"] == "0.003500"

    def test_null_cost_does_not_break_sum(self):
        rows = [
            self._row(cost_usd=None),
            self._row(cost_usd="0.000123"),
        ]
        t = compute_totals(rows)
        assert t["cost_usd"] == "0.000123"


# ---------------------------------------------------------------------------
# sort_rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSortRows:
    @staticmethod
    def _row(**overrides):
        defaults = {
            "bucket_start": "2026-05-26",
            "group_key": "a",
            "group_label": "A",
            "request_count": 1,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_usd": "0.000100",
        }
        defaults.update(overrides)
        return defaults

    def test_default_sort_by_bucket_desc(self):
        rows = [
            self._row(bucket_start="2026-05-26"),
            self._row(bucket_start="2026-05-19"),
            self._row(bucket_start="2026-05-12"),
        ]
        sorted_rows = sort_rows(rows, "bucket_start", "desc")
        assert [r["bucket_start"] for r in sorted_rows] == [
            "2026-05-26",
            "2026-05-19",
            "2026-05-12",
        ]

    def test_sort_by_cost_uses_decimal_comparison(self):
        """String cost values must order numerically, not lexically."""
        rows = [
            self._row(cost_usd="9.999999"),
            self._row(cost_usd="10.000000"),
            self._row(cost_usd="0.000100"),
        ]
        sorted_rows = sort_rows(rows, "cost_usd", "desc")
        assert [r["cost_usd"] for r in sorted_rows] == [
            "10.000000",
            "9.999999",
            "0.000100",
        ]

    def test_unknown_sort_falls_back_to_bucket(self):
        rows = [
            self._row(bucket_start="2026-05-19"),
            self._row(bucket_start="2026-05-26"),
        ]
        sorted_rows = sort_rows(rows, "not-a-real-column", "desc")
        # Still ordered, just by bucket_start.
        assert [r["bucket_start"] for r in sorted_rows] == [
            "2026-05-26",
            "2026-05-19",
        ]

    def test_ascending(self):
        rows = [
            self._row(request_count=10),
            self._row(request_count=2),
            self._row(request_count=5),
        ]
        sorted_rows = sort_rows(rows, "request_count", "asc")
        assert [r["request_count"] for r in sorted_rows] == [2, 5, 10]


@pytest.mark.unit
def test_sort_keys_match_response_columns():
    """Drift guard: every sort key has a matching field in the response row."""
    response_columns = {
        "bucket_start",
        "group_label",
        "request_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "energy_kwh_max",
        "gwp_kgco2eq_max",
        "water_l_max",
    }
    assert _SORT_KEYS == response_columns


# NOTE on hermeticity: every test in this module operates on synthetic
# fixtures only — no SQLAlchemy session, no asyncpg, no live DB query,
# no reference to the wall clock other than the bounded ``delta``-based
# assertions in ``TestResolveDateRange``. Future tests added here must
# preserve that property; live-DB assertions belong in
# ``tests/integration/`` against a seeded fixture so the expected
# results are stable across runs even as new activity is logged.


# ---------------------------------------------------------------------------
# Estimated footprint (migration 0042) and the pipeline's own line
# ---------------------------------------------------------------------------


class TestFootprintRollup:
    @staticmethod
    def _row(**overrides):
        row = TestComputeTotals._row()
        row.update(overrides)
        return row

    def test_row_carries_sums_as_floats(self):
        estimated = TestRowToDict()._row(
            energy_kwh_min=Decimal("0.0001"),
            energy_kwh_max=Decimal("0.0003"),
            footprint_unestimated_tokens=40,
        )
        out = _row_to_dict(estimated)
        assert (out["energy_kwh_min"], out["energy_kwh_max"]) == (0.0001, 0.0003)
        assert isinstance(out["energy_kwh_min"], float)
        assert out["footprint_unestimated_tokens"] == 40

    def test_totals_sum_the_estimates_and_unestimated_tokens(self):
        rows = [
            self._row(
                energy_kwh_min=1.0, energy_kwh_max=2.0, footprint_unestimated_tokens=5
            ),
            self._row(
                energy_kwh_min=0.5, energy_kwh_max=1.0, footprint_unestimated_tokens=7
            ),
            self._row(),  # no estimate: left out of the sums, not counted as 0
        ]
        t = compute_totals(rows)
        assert (t["energy_kwh_min"], t["energy_kwh_max"]) == (1.5, 3.0)
        assert t["footprint_unestimated_tokens"] == 12
        assert t["water_l_min"] is None

    def test_sorting_puts_rows_with_no_estimate_last(self):
        rows = [
            self._row(group_label="none"),
            self._row(group_label="small", gwp_kgco2eq_max=0.1),
            self._row(group_label="big", gwp_kgco2eq_max=0.9),
        ]
        desc = [r["group_label"] for r in sort_rows(rows, "gwp_kgco2eq_max", "desc")]
        assert desc == ["big", "small", "none"]

    @pytest.mark.parametrize(
        "builder", [_build_user_grouped_sql, _build_group_grouped_sql]
    )
    def test_both_groupings_sum_the_footprint_and_give_pipeline_its_own_line(
        self, builder
    ):
        sql = builder("week", None)
        for column in _FOOTPRINT_COLUMNS:
            assert f"AS {column}" in sql
        assert "AS footprint_unestimated_tokens" in sql
        # Ingestion has no user or group: its rows get their own line.
        assert "'(pipeline)'" in sql
        assert "filters->>'type', '') = 'pipeline'" in sql
