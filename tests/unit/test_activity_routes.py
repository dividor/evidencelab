"""Tests for activity route helpers and JSONB merge logic."""

import copy
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ui.backend.routes.activity import (
    _SORT_COL_MAP,
    _activity_to_read,
    _apply_summary_fields,
    _apply_token_usage,
    _build_activity_items,
    _build_export_row,
    _count_search_results,
    _find_existing_activity,
    _merge_filters_update,
    _ms_to_seconds,
    _resolve_cost,
    log_activity,
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
        "llm_model": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
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
        from decimal import Decimal

        user = _make_user()
        activity = _make_activity(
            query="water sanitation",
            search_results=[{"id": 1}],
            ai_summary="A short summary.",
            url="https://example.com",
            has_ratings=True,
            filters={"timing": {"search_duration_ms": 1500}},
            llm_model="gpt-4.1-mini",
            prompt_tokens=1200,
            completion_tokens=350,
            cost_usd=Decimal("0.001040"),
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
        assert row[8] == "gpt-4.1-mini"
        assert row[9] == 1200
        assert row[10] == 350
        assert row[11] == 0.00104  # Decimal('0.001040') → float
        assert row[12] == "A short summary."
        assert row[13] == "https://example.com"
        assert row[14] == "Yes"

    def test_long_summary_truncated(self):
        long_summary = "x" * 1500
        activity = _make_activity(ai_summary=long_summary)
        row = _build_export_row(activity, None)
        assert len(row[12]) <= 1000
        assert row[12].endswith("...")

    def test_null_user(self):
        activity = _make_activity()
        row = _build_export_row(activity, None)
        assert row[1] == "(anonymous)"  # email
        assert row[2] == "Anonymous"  # display name

    def test_no_created_at(self):
        activity = _make_activity(created_at=None)
        row = _build_export_row(activity, None)
        assert row[0] == ""

    def test_null_cost_keeps_none(self):
        """Empty cost cell stays None (not 0.0) so XLSX renders blank."""
        activity = _make_activity(llm_model="gpt-4.1-mini", prompt_tokens=10)
        row = _build_export_row(activity, None)
        assert row[8] == "gpt-4.1-mini"
        assert row[9] == 10
        assert row[10] is None
        assert row[11] is None


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


# ---------------------------------------------------------------------------
# _activity_to_read with token-usage fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActivityToReadTokenUsage:
    """Token-usage round-trip through _activity_to_read."""

    def test_token_fields_pass_through(self):
        activity = _make_activity(
            llm_model="gpt-4.1-mini",
            prompt_tokens=2000,
            completion_tokens=500,
            cost_usd=Decimal("0.001600"),
        )
        result = _activity_to_read(activity)
        assert result.llm_model == "gpt-4.1-mini"
        assert result.prompt_tokens == 2000
        assert result.completion_tokens == 500
        assert result.cost_usd == Decimal("0.001600")

    def test_null_token_fields_render_as_none(self):
        """Historical rows (all None) round-trip cleanly."""
        activity = _make_activity()
        result = _activity_to_read(activity)
        assert result.llm_model is None
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.cost_usd is None


# ---------------------------------------------------------------------------
# _resolve_cost
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveCost:
    """The route helper that prefers server-computed cost over client input."""

    def test_server_overrides_client(self):
        """Even if the client lies about cost, the server recomputes."""
        # gpt-4.1-mini at 1000/500 tokens computes to 0.001200; client lies.
        result = _resolve_cost(Decimal("999"), "gpt-4.1-mini", 1000, 500)
        assert result == Decimal("0.001200")

    def test_falls_back_to_client_when_model_unknown(self):
        """For models without rates, we trust the client-supplied value."""
        result = _resolve_cost(Decimal("0.05"), "not-a-real-model", 1000, 500)
        assert result == Decimal("0.05")

    def test_all_none(self):
        """With nothing to work from, returns None."""
        assert _resolve_cost(None, None, None, None) is None

    def test_client_none_unknown_model_no_tokens(self):
        """Unknown model + no tokens + no client value → None."""
        assert _resolve_cost(None, "unknown", None, None) is None


# ---------------------------------------------------------------------------
# _apply_token_usage  (PATCH route helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyTokenUsage:
    """End-to-end behaviour of the PATCH helper."""

    @staticmethod
    def _body(**fields):
        defaults = {
            "llm_model": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_usd": None,
        }
        defaults.update(fields)
        return SimpleNamespace(**defaults)

    def test_writes_model_tokens_and_computed_cost(self):
        """A full usage payload populates all four columns; server recomputes cost."""
        activity = _make_activity()
        body = self._body(
            llm_model="gpt-4.1-mini",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=Decimal("0.05"),  # client-supplied lie
        )
        _apply_token_usage(activity, body)
        assert activity.llm_model == "gpt-4.1-mini"
        assert activity.prompt_tokens == 1000
        assert activity.completion_tokens == 500
        assert activity.cost_usd == Decimal("0.001200")  # server-computed

    def test_no_op_when_payload_empty(self):
        """If no usage fields are submitted, leave the activity alone."""
        activity = _make_activity(
            llm_model="prev-model",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=Decimal("0.0001"),
        )
        body = self._body()
        _apply_token_usage(activity, body)
        # Unchanged.
        assert activity.llm_model == "prev-model"
        assert activity.prompt_tokens == 10
        assert activity.completion_tokens == 5
        assert activity.cost_usd == Decimal("0.0001")

    def test_partial_update_only_overwrites_provided_fields(self):
        """Partial PATCHes (model + tokens, no cost) still trigger recompute."""
        activity = _make_activity(cost_usd=Decimal("999"))
        body = self._body(
            llm_model="gpt-4.1-mini",
            prompt_tokens=1000,
            completion_tokens=0,
        )
        _apply_token_usage(activity, body)
        assert activity.cost_usd == Decimal("0.000400")

    def test_unknown_model_keeps_client_cost(self):
        """When model has no rate, persist whatever cost the client sent."""
        activity = _make_activity()
        body = self._body(
            llm_model="custom-model",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=Decimal("0.123456"),
        )
        _apply_token_usage(activity, body)
        assert activity.cost_usd == Decimal("0.123456")


# ---------------------------------------------------------------------------
# Sort map
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSortColMap:
    """The sort_by whitelist must include the new token-usage columns."""

    def test_new_sort_keys_present(self):
        for key in ("llm_model", "total_tokens", "cost_usd"):
            assert key in _SORT_COL_MAP, f"{key} missing from sort map"

    def test_sort_columns_are_callable_factories(self):
        """Each entry must be a lambda returning a SQLAlchemy expression."""
        for key, factory in _SORT_COL_MAP.items():
            assert callable(factory), f"{key} sort entry must be callable"


# ---------------------------------------------------------------------------
# _apply_summary_fields + _merge_filters_update  (helpers extracted from route)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplySummaryFields:
    def test_writes_summary_when_provided(self):
        activity = _make_activity(ai_summary="old")
        body = SimpleNamespace(ai_summary="new")
        _apply_summary_fields(activity, body)
        assert activity.ai_summary == "new"

    def test_leaves_summary_when_none(self):
        activity = _make_activity(ai_summary="kept")
        body = SimpleNamespace(ai_summary=None)
        _apply_summary_fields(activity, body)
        assert activity.ai_summary == "kept"


@pytest.mark.unit
class TestMergeFiltersUpdate:
    def test_merges_timing_into_empty_filters(self):
        activity = _make_activity(filters=None)
        body = SimpleNamespace(summary_duration_ms=1500.0, drilldown_tree=None)
        _merge_filters_update(activity, body)
        assert activity.filters == {"timing": {"summary_duration_ms": 1500.0}}

    def test_no_op_when_nothing_to_merge(self):
        original = {"existing": True}
        activity = _make_activity(filters=original)
        body = SimpleNamespace(summary_duration_ms=None, drilldown_tree=None)
        _merge_filters_update(activity, body)
        assert activity.filters is original


def _brief_body(search_id, **overrides):
    """A POST /activity body for a Brief save (type='brief')."""
    defaults = {
        "search_id": str(search_id),
        "query": "Brief Title",
        "filters": {"type": "brief"},
        "search_results": [{"doc_id": "d1"}],
        "ai_summary": "## Heading\n\nBody",
        "url": "http://app/brief",
        "session_id": "sess-1",
        "llm_model": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_session():
    return SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())


@pytest.mark.unit
class TestLogActivityUpsert:
    """POST /activity/ upserts by (owner, search_id) — the Brief tab relies on
    this to keep one activity row per brief, refreshed on each save."""

    @pytest.mark.asyncio
    async def test_updates_existing_row_in_place(self):
        sid = uuid.uuid4()
        existing = _make_activity(search_id=sid, query="old", filters=None)
        body = _brief_body(sid)
        session = _fake_session()
        with patch(
            "ui.backend.routes.activity._find_existing_activity",
            new=AsyncMock(return_value=existing),
        ):
            await log_activity(body, user=None, session=session)
        # Row mutated in place, no new row inserted.
        assert existing.query == "Brief Title"
        assert existing.filters == {"type": "brief"}
        assert existing.ai_summary == "## Heading\n\nBody"
        session.add.assert_not_called()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inserts_when_no_existing_row(self):
        body = _brief_body(uuid.uuid4())
        session = _fake_session()
        with patch(
            "ui.backend.routes.activity._find_existing_activity",
            new=AsyncMock(return_value=None),
        ), patch("ui.backend.routes.activity._activity_to_read", return_value="ok"):
            result = await log_activity(body, user=None, session=session)
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_update_preserves_server_recorded_usage_when_omitted(self):
        """Regression: a re-POST without usage (every Brief save) must not
        null out token counts recorded server-side by the streaming routes."""
        sid = uuid.uuid4()
        existing = _make_activity(
            search_id=sid,
            llm_model="gpt-4.1-mini",
            prompt_tokens=1200,
            completion_tokens=300,
            cost_usd=Decimal("0.000960"),
        )
        body = _brief_body(sid)  # no usage fields
        session = _fake_session()
        with patch(
            "ui.backend.routes.activity._find_existing_activity",
            new=AsyncMock(return_value=existing),
        ):
            await log_activity(body, user=None, session=session)
        assert existing.llm_model == "gpt-4.1-mini"
        assert existing.prompt_tokens == 1200
        assert existing.completion_tokens == 300
        assert existing.cost_usd == Decimal("0.000960")

    @pytest.mark.asyncio
    async def test_update_applies_usage_when_provided(self):
        """A re-POST that does carry usage still overwrites (patch semantics)."""
        sid = uuid.uuid4()
        existing = _make_activity(search_id=sid, prompt_tokens=10)
        body = _brief_body(
            sid, llm_model="gpt-4.1-mini", prompt_tokens=500, completion_tokens=100
        )
        session = _fake_session()
        with patch(
            "ui.backend.routes.activity._find_existing_activity",
            new=AsyncMock(return_value=existing),
        ):
            await log_activity(body, user=None, session=session)
        assert existing.prompt_tokens == 500
        assert existing.completion_tokens == 100
        assert existing.llm_model == "gpt-4.1-mini"
        assert existing.cost_usd is not None

    @pytest.mark.asyncio
    async def test_does_not_blank_summary_when_omitted(self):
        sid = uuid.uuid4()
        existing = _make_activity(search_id=sid, ai_summary="keep me")
        body = _brief_body(sid, ai_summary=None)
        session = _fake_session()
        with patch(
            "ui.backend.routes.activity._find_existing_activity",
            new=AsyncMock(return_value=existing),
        ):
            await log_activity(body, user=None, session=session)
        assert existing.ai_summary == "keep me"

    @pytest.mark.asyncio
    async def test_find_existing_returns_none_without_owner(self):
        session = SimpleNamespace(execute=AsyncMock())
        result = await _find_existing_activity(
            session, user=None, session_id=None, search_uuid=uuid.uuid4()
        )
        assert result is None
        session.execute.assert_not_called()


@pytest.mark.unit
def test_brief_is_a_valid_activity_type():
    from ui.backend.routes.llm_usage import _VALID_ACTIVITY_TYPES

    assert "brief" in _VALID_ACTIVITY_TYPES
