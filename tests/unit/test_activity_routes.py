"""Tests for activity route helpers and JSONB merge logic."""

import copy
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from ui.backend.routes.activity import (
    _activity_to_read,
    _build_activity_items,
    _build_export_row,
    _count_search_results,
    _ms_to_seconds,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_activity(**overrides):
    """Create a mock UserActivity ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "session_id": None,
        "search_id": uuid.uuid4(),
        "query": "test query",
        "filters": None,
        "search_results": None,
        "ai_summary": None,
        "url": None,
        "has_ratings": False,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user(**overrides):
    """Create a mock User object."""
    defaults = {
        "id": uuid.uuid4(),
        "email": "user@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    # Add full_name property to mimic the ORM model
    parts = [p for p in (ns.first_name, ns.last_name) if p]
    ns.full_name = " ".join(parts) if parts else None
    return ns


# ---------------------------------------------------------------------------
# _activity_to_read
# ---------------------------------------------------------------------------


class TestActivityToRead:
    """Tests for the _activity_to_read helper."""

    def test_basic_conversion(self):
        """Converts ORM object to ActivityRead with user info."""
        user = _make_user()
        activity = _make_activity(user_id=user.id)
        result = _activity_to_read(activity, user)
        assert result.user_email == "user@example.com"
        assert result.user_display_name == "Test User"
        assert result.query == "test query"
        assert result.has_ratings is False

    def test_without_user(self):
        """Works when user is None (e.g. deleted user)."""
        activity = _make_activity()
        result = _activity_to_read(activity, None)
        assert result.user_email is None
        assert result.user_display_name is None

    def test_preserves_filters(self):
        """Filters dict passes through to ActivityRead."""
        filters = {"timing": {"search_duration_ms": 450}}
        activity = _make_activity(filters=filters)
        result = _activity_to_read(activity)
        assert result.filters == filters

    def test_preserves_search_results(self):
        """Search results list passes through to ActivityRead."""
        results = [{"chunk_id": "c1", "title": "Report 1"}]
        activity = _make_activity(search_results=results)
        result = _activity_to_read(activity)
        assert result.search_results == results


# ---------------------------------------------------------------------------
# _ms_to_seconds
# ---------------------------------------------------------------------------


class TestMsToSeconds:
    """Tests for the _ms_to_seconds helper."""

    def test_normal_conversion(self):
        assert _ms_to_seconds(1500.0) == 1.5

    def test_fractional(self):
        assert _ms_to_seconds(1234.5) == 1.23

    def test_zero(self):
        assert _ms_to_seconds(0) is None  # falsy → None

    def test_none(self):
        assert _ms_to_seconds(None) is None

    def test_small_value(self):
        assert _ms_to_seconds(50.0) == 0.05


# ---------------------------------------------------------------------------
# _count_search_results
# ---------------------------------------------------------------------------


class TestCountSearchResults:
    """Tests for the _count_search_results helper."""

    def test_list_format(self):
        activity = _make_activity(search_results=[{"id": 1}, {"id": 2}, {"id": 3}])
        assert _count_search_results(activity) == 3

    def test_dict_format(self):
        activity = _make_activity(
            search_results={"results": [{"id": 1}, {"id": 2}], "total": 100}
        )
        assert _count_search_results(activity) == 2

    def test_none(self):
        activity = _make_activity(search_results=None)
        assert _count_search_results(activity) == 0

    def test_empty_list(self):
        activity = _make_activity(search_results=[])
        assert _count_search_results(activity) == 0

    def test_dict_missing_results_key(self):
        activity = _make_activity(search_results={"total": 5})
        assert _count_search_results(activity) == 0


# ---------------------------------------------------------------------------
# _build_export_row
# ---------------------------------------------------------------------------


class TestBuildExportRow:
    """Tests for the _build_export_row helper."""

    def test_basic_row(self):
        user = _make_user()
        activity = _make_activity(
            query="water sanitation",
            search_results=[{"id": 1}],
            ai_summary="A short summary.",
            url="https://example.com",
            has_ratings=True,
            filters={"timing": {"search_duration_ms": 1500}},
        )
        row = _build_export_row(activity, user)
        assert row[0] == "2026-03-01 12:00"  # formatted date
        assert row[1] == "user@example.com"
        assert row[2] == "Test User"
        assert row[3] == "water sanitation"
        assert row[4] == 1  # result count
        assert row[5] == 1.5  # search time seconds
        assert row[6] is None  # no summary time
        assert row[7] is None  # no heatmap time
        assert row[8] == "A short summary."
        assert row[9] == "https://example.com"
        assert row[10] == "Yes"

    def test_long_summary_truncated(self):
        long_summary = "x" * 1500
        activity = _make_activity(ai_summary=long_summary)
        row = _build_export_row(activity, None)
        assert len(row[8]) <= 1000
        assert row[8].endswith("...")

    def test_null_user(self):
        activity = _make_activity()
        row = _build_export_row(activity, None)
        assert row[1] == "(anonymous)"  # email
        assert row[2] == "Anonymous"  # display name

    def test_no_created_at(self):
        activity = _make_activity(created_at=None)
        row = _build_export_row(activity, None)
        assert row[0] == ""


# ---------------------------------------------------------------------------
# _build_activity_items
# ---------------------------------------------------------------------------


class TestBuildActivityItems:
    """Tests for the _build_activity_items helper."""

    def test_enriches_has_ratings(self):
        """Items whose search_id is in rated_ids get has_ratings=True."""
        sid = uuid.uuid4()
        activity = _make_activity(search_id=sid, has_ratings=False)
        user = _make_user()
        rows = [(activity, user)]
        rated_ids = {str(sid)}
        items = _build_activity_items(rows, rated_ids)
        assert len(items) == 1
        assert items[0]["has_ratings"] is True

    def test_unrated_stays_false(self):
        """Items not in rated_ids keep has_ratings=False."""
        activity = _make_activity(has_ratings=False)
        user = _make_user()
        rows = [(activity, user)]
        items = _build_activity_items(rows, set())
        assert items[0]["has_ratings"] is False

    def test_empty_rows(self):
        items = _build_activity_items([], set())
        assert items == []


# ---------------------------------------------------------------------------
# JSONB merge logic (update_activity_summary)
# ---------------------------------------------------------------------------


class TestActivitySummaryMerge:
    """Tests for the JSONB merge logic in update_activity_summary.

    We test the merge logic directly rather than through async HTTP,
    replicating the exact code path from the route handler.
    """

    @staticmethod
    def _merge_summary(activity, body):
        """Replicate the merge logic from update_activity_summary."""
        if body.ai_summary is not None:
            activity.ai_summary = body.ai_summary

        if body.summary_duration_ms is not None or body.drilldown_tree is not None:
            merged = copy.deepcopy(activity.filters or {})
            if body.summary_duration_ms is not None:
                timing = merged.get("timing", {})
                timing["summary_duration_ms"] = body.summary_duration_ms
                merged["timing"] = timing
            if body.drilldown_tree is not None:
                merged["drilldown_tree"] = body.drilldown_tree
            activity.filters = merged

    def test_summary_text_only(self):
        """Updating just ai_summary doesn't touch filters."""
        activity = _make_activity(filters={"existing": True})
        body = SimpleNamespace(
            ai_summary="New summary",
            summary_duration_ms=None,
            drilldown_tree=None,
        )
        self._merge_summary(activity, body)
        assert activity.ai_summary == "New summary"
        assert activity.filters == {"existing": True}

    def test_timing_into_empty_filters(self):
        """Timing merges into None filters, creating timing sub-object."""
        activity = _make_activity(filters=None)
        body = SimpleNamespace(
            ai_summary=None,
            summary_duration_ms=1500.0,
            drilldown_tree=None,
        )
        self._merge_summary(activity, body)
        assert activity.filters == {"timing": {"summary_duration_ms": 1500.0}}

    def test_timing_preserves_existing_timing(self):
        """summary_duration_ms merges alongside existing search_duration_ms."""
        activity = _make_activity(filters={"timing": {"search_duration_ms": 450}})
        body = SimpleNamespace(
            ai_summary=None,
            summary_duration_ms=2000.0,
            drilldown_tree=None,
        )
        self._merge_summary(activity, body)
        timing = activity.filters["timing"]
        assert timing["search_duration_ms"] == 450
        assert timing["summary_duration_ms"] == 2000.0

    def test_drilldown_tree_merge(self):
        """Drilldown tree gets added to filters."""
        activity = _make_activity(filters={"timing": {"search_duration_ms": 100}})
        tree = {"id": "root", "label": "Summary", "children": []}
        body = SimpleNamespace(
            ai_summary=None,
            summary_duration_ms=None,
            drilldown_tree=tree,
        )
        self._merge_summary(activity, body)
        assert activity.filters["drilldown_tree"] == tree
        assert activity.filters["timing"]["search_duration_ms"] == 100

    def test_both_timing_and_tree(self):
        """Both timing and tree can be set in the same update."""
        activity = _make_activity(filters=None)
        tree = {
            "id": "r",
            "label": "Root",
            "children": [{"id": "c1", "label": "Child"}],
        }
        body = SimpleNamespace(
            ai_summary="Full summary",
            summary_duration_ms=3000.0,
            drilldown_tree=tree,
        )
        self._merge_summary(activity, body)
        assert activity.ai_summary == "Full summary"
        assert activity.filters["timing"]["summary_duration_ms"] == 3000.0
        assert activity.filters["drilldown_tree"]["id"] == "r"

    def test_deep_copy_isolation(self):
        """Mutating merged filters must not affect original dict reference."""
        original_filters = {"timing": {"search_duration_ms": 100}, "other": "data"}
        activity = _make_activity(filters=original_filters)
        body = SimpleNamespace(
            ai_summary=None,
            summary_duration_ms=500.0,
            drilldown_tree=None,
        )
        # Keep a reference to original nested dict
        original_timing_ref = original_filters["timing"]
        self._merge_summary(activity, body)
        # The activity's filters should be a new object
        assert activity.filters is not original_filters
        # Original timing dict should NOT have been mutated
        assert "summary_duration_ms" not in original_timing_ref

    def test_no_op_when_all_none(self):
        """When all update fields are None, filters stay untouched."""
        original = {"existing": True}
        activity = _make_activity(filters=original)
        body = SimpleNamespace(
            ai_summary=None,
            summary_duration_ms=None,
            drilldown_tree=None,
        )
        self._merge_summary(activity, body)
        assert activity.filters is original  # same reference, no copy
