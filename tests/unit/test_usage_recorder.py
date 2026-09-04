"""Tests for the server-side LLM usage recorder
(``ui.backend.services.usage_recorder``)."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ui.backend.services.usage_recorder import has_usage, record_llm_usage, usage_cost

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    """Async-context-manager session stub for the recorder's upsert path."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.first.return_value = self.existing
        return result

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True


def _factory(session):
    return lambda: session


def _existing_row(**overrides):
    defaults = {
        "user_id": None,
        "session_id": "sess-1",
        "search_id": uuid.uuid4(),
        "filters": {"type": "brief"},
        "llm_model": "gpt-4.1-mini",
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "cost_usd": Decimal("0.000720"),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


_USAGE = {"llm_model": "gpt-4.1-mini", "prompt_tokens": 1000, "completion_tokens": 500}
# 1000 * 0.0004/1k + 500 * 0.0016/1k
_USAGE_COST = Decimal("0.001200")


# ---------------------------------------------------------------------------
# has_usage / usage_cost
# ---------------------------------------------------------------------------


class TestUsagePayloadHelpers:
    def test_has_usage_when_tokens_present_then_true(self):
        assert has_usage({"prompt_tokens": 1}) is True
        assert has_usage({"completion_tokens": 2}) is True

    def test_has_usage_when_empty_or_model_only_then_false(self):
        assert has_usage(None) is False
        assert has_usage({}) is False
        assert has_usage({"llm_model": "gpt-4.1-mini"}) is False
        assert has_usage({"prompt_tokens": 0, "completion_tokens": 0}) is False

    def test_has_usage_when_malformed_counts_then_false(self):
        assert has_usage({"prompt_tokens": "abc"}) is False
        assert has_usage({"prompt_tokens": -5}) is False

    def test_usage_cost_matches_pricing_table(self):
        assert usage_cost(_USAGE) == _USAGE_COST

    def test_usage_cost_unknown_model_is_none(self):
        assert usage_cost({"llm_model": "mystery", "prompt_tokens": 10}) is None


# ---------------------------------------------------------------------------
# record_llm_usage
# ---------------------------------------------------------------------------


class TestRecordLlmUsage:
    @pytest.mark.asyncio
    async def test_record_when_no_tokens_then_skips(self):
        session = _FakeSession()
        recorded = await record_llm_usage(
            usage={"llm_model": "gpt-4.1-mini"},
            activity_type="evaluation",
            query="q",
            session_factory=_factory(session),
        )
        assert recorded is False
        assert session.added == []
        assert session.committed is False

    @pytest.mark.asyncio
    async def test_record_when_no_existing_row_then_inserts_typed_row(self):
        session = _FakeSession(existing=None)
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()
        recorded = await record_llm_usage(
            usage=_USAGE,
            activity_type="evaluation",
            query="Evaluation: exp (run 3)",
            user_id=user_id,
            search_id=run_id,
            filters_extra={"run_number": 3},
            session_factory=_factory(session),
        )
        assert recorded is True
        assert session.committed is True
        (row,) = session.added
        assert row.search_id == run_id
        assert row.user_id == user_id
        assert row.query == "Evaluation: exp (run 3)"
        assert row.filters == {"run_number": 3, "type": "evaluation"}
        assert row.llm_model == "gpt-4.1-mini"
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 500
        assert row.cost_usd == _USAGE_COST

    @pytest.mark.asyncio
    async def test_record_when_row_exists_then_accumulates(self):
        existing = _existing_row()
        session = _FakeSession(existing=existing)
        recorded = await record_llm_usage(
            usage=_USAGE,
            activity_type="brief",
            query="ignored for existing rows",
            session_id="sess-1",
            search_id=existing.search_id,
            session_factory=_factory(session),
        )
        assert recorded is True
        assert session.added == []  # accumulated in place, no new row
        assert existing.prompt_tokens == 2000
        assert existing.completion_tokens == 700
        assert existing.cost_usd == Decimal("0.000720") + _USAGE_COST
        # Existing filters are never touched on accumulation.
        assert existing.filters == {"type": "brief"}

    @pytest.mark.asyncio
    async def test_record_when_model_unknown_then_tokens_without_cost(self):
        session = _FakeSession(existing=None)
        recorded = await record_llm_usage(
            usage={"llm_model": "qwen2.5-7b-instruct", "prompt_tokens": 50},
            activity_type="mcp-assistant",
            query="q",
            session_factory=_factory(session),
        )
        assert recorded is True
        (row,) = session.added
        assert row.prompt_tokens == 50
        assert row.cost_usd is None

    @pytest.mark.asyncio
    async def test_record_when_cost_precomputed_then_not_recomputed(self):
        session = _FakeSession(existing=None)
        await record_llm_usage(
            usage=_USAGE,
            activity_type="evaluation",
            query="q",
            cost_usd=Decimal("9.999999"),
            session_factory=_factory(session),
        )
        (row,) = session.added
        assert row.cost_usd == Decimal("9.999999")

    @pytest.mark.asyncio
    async def test_record_when_search_id_invalid_then_new_row_still_written(self):
        session = _FakeSession(existing=None)
        recorded = await record_llm_usage(
            usage=_USAGE,
            activity_type="highlight",
            query="q",
            search_id="not-a-uuid",
            session_factory=_factory(session),
        )
        assert recorded is True
        (row,) = session.added
        assert isinstance(row.search_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_record_when_session_factory_raises_then_swallows(self):
        def _boom():
            raise RuntimeError("db down")

        recorded = await record_llm_usage(
            usage=_USAGE,
            activity_type="evaluation",
            query="q",
            session_factory=_boom,
        )
        assert recorded is False

    @pytest.mark.asyncio
    async def test_record_anonymous_row_keeps_session_id(self):
        session = _FakeSession(existing=None)
        await record_llm_usage(
            usage=_USAGE,
            activity_type=None,
            query="plain search summary",
            session_id="sess-9",
            search_id=uuid.uuid4(),
            session_factory=_factory(session),
        )
        (row,) = session.added
        assert row.user_id is None
        assert row.session_id == "sess-9"
        # No type → the row defaults to 'search' semantics (no filters).
        assert row.filters is None


# ---------------------------------------------------------------------------
# Owner scoping — a client-supplied id never matches another owner's row
# ---------------------------------------------------------------------------


class TestOwnerScoping:
    @pytest.mark.asyncio
    async def test_lookup_is_owner_scoped(self):
        """The SELECT must constrain on user_id (or session_id) when given."""
        captured = {}

        class _CapturingSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = str(stmt)
                return await super().execute(stmt)

        session = _CapturingSession(existing=None)
        user_id = uuid.uuid4()
        await record_llm_usage(
            usage=_USAGE,
            activity_type=None,
            query="q",
            user_id=user_id,
            search_id=uuid.uuid4(),
            session_factory=_factory(session),
        )
        assert "user_id" in captured["stmt"]

    @pytest.mark.asyncio
    async def test_lookup_scopes_by_session_when_anonymous(self):
        captured = {}

        class _CapturingSession(_FakeSession):
            async def execute(self, stmt):
                captured["stmt"] = str(stmt)
                return await super().execute(stmt)

        session = _CapturingSession(existing=None)
        await record_llm_usage(
            usage=_USAGE,
            activity_type=None,
            query="q",
            session_id="sess-1",
            search_id=uuid.uuid4(),
            session_factory=_factory(session),
        )
        assert "session_id" in captured["stmt"]


# ---------------------------------------------------------------------------
# server_owned matching + background scheduling
# ---------------------------------------------------------------------------


class TestServerOwnedMatching:
    @pytest.mark.asyncio
    async def test_client_id_without_owner_never_matches_existing_row(self):
        """A client-supplied id with no owner context must not accumulate onto
        an existing row (cross-owner pollution guard) — it gets a fresh row."""
        existing = _existing_row(user_id=uuid.uuid4(), session_id=None)
        session = _FakeSession(existing=existing)
        await record_llm_usage(
            usage=_USAGE,
            activity_type=None,
            query="q",
            search_id=existing.search_id,  # attacker-guessed id, no owner
            session_factory=_factory(session),
        )
        # Existing row untouched; the usage landed on a new row instead.
        assert existing.prompt_tokens == 1000
        (row,) = session.added
        assert row.prompt_tokens == 1000

    @pytest.mark.asyncio
    async def test_server_owned_id_matches_existing_row_without_owner(self):
        existing = _existing_row(user_id=None, session_id=None)
        session = _FakeSession(existing=existing)
        await record_llm_usage(
            usage=_USAGE,
            activity_type="evaluation",
            query="q",
            search_id=existing.search_id,
            server_owned=True,
            session_factory=_factory(session),
        )
        assert session.added == []
        assert existing.prompt_tokens == 2000


class TestBackgroundScheduling:
    @pytest.mark.asyncio
    async def test_schedule_records_in_background(self):
        import asyncio

        from ui.backend.services.usage_recorder import schedule_llm_usage_recording

        session = _FakeSession(existing=None)
        schedule_llm_usage_recording(
            usage=_USAGE,
            activity_type="brief",
            query="q",
            session_id="sess-1",
            session_factory=_factory(session),
        )
        # The write happens off the caller's path; let the task run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert session.committed is True
        (row,) = session.added
        assert row.prompt_tokens == 1000

    def test_schedule_without_running_loop_never_raises(self):
        from ui.backend.services.usage_recorder import schedule_llm_usage_recording

        # No running event loop here — scheduling must swallow, not raise.
        schedule_llm_usage_recording(usage=_USAGE, activity_type="brief", query="q")
