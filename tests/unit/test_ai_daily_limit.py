"""Tests for the site's daily AI limit (``ui.backend.services.ai_daily_limit``)."""

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from ui.backend.services import ai_daily_limit as limit_mod
from ui.backend.services.ai_daily_limit import (
    LIMIT_ENV,
    LIMIT_MESSAGE,
    LIMIT_REACHED_LOG,
    PRICES_FILE,
    AiDailyLimitReached,
    add_to_daily_spend,
    ai_daily_limit_handler,
    check_ai_allowance,
    configured_llm_names,
    daily_limit,
    require_ai_allowance,
    seconds_until_utc_midnight,
    spent_on,
    validate_ai_daily_limit_setting,
)

pytestmark = pytest.mark.unit

NOON = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


class _Session:
    """Async session stub: returns ``spent`` for the day's total and records
    every statement it is given."""

    def __init__(self, spent=None):
        self.spent = spent
        self.statements = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self.statements.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.spent
        return result

    async def commit(self):
        self.committed = True


class _Factory:
    def __init__(self, spent=None):
        self.session = _Session(spent)
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self.session


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.delenv(LIMIT_ENV, raising=False)
    monkeypatch.setattr(
        limit_mod,
        "_cache",
        {"day": None, "spent": Decimal(0), "read_at": float("-inf")},
    )
    monkeypatch.setattr(limit_mod, "_logged_day", None)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


_NOVA_ID = "us.amazon.nova-2-lite-v1:0"


def _use_config(monkeypatch, supported_llms, combos=None):
    """Run the real start-up check against these config.json model sections."""
    monkeypatch.setattr(limit_mod.db_config, "SUPPORTED_LLMS", supported_llms)
    monkeypatch.setattr(limit_mod.db_config, "UI_MODEL_COMBOS", combos or {})


@pytest.fixture
def priced_config(monkeypatch):
    """A config.json whose models all have a price in llm_costs.py."""
    _use_config(
        monkeypatch,
        {
            "nova-2-lite": {"model": _NOVA_ID, "provider": "aws_bedrock"},
            "gpt-4.1-mini": {"model": "gpt-4.1-mini", "provider": "azure_foundry"},
        },
        {
            "AWS Bedrock": {
                "summarization_model": {"model": "nova-2-lite"},
                "semantic_highlighting_model": {"model": "nova-2-lite"},
                "assistant_model": {"model": "nova-2-lite"},
            }
        },
    )


@pytest.fixture
def unpriced_config(monkeypatch):
    """A config.json listing one model llm_costs.py has no price for."""
    _use_config(
        monkeypatch,
        {
            "nova-2-lite": {"model": _NOVA_ID, "provider": "aws_bedrock"},
            "mystery-llm": {"model": "org/Mystery-LLM", "provider": "huggingface"},
        },
    )


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


class TestDailyLimitSetting:
    def test_daily_limit_when_unset_then_none(self):
        assert daily_limit() is None

    def test_daily_limit_when_blank_then_none(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "  ")
        assert daily_limit() is None

    def test_daily_limit_when_dollars_then_decimal(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "25.50")
        assert daily_limit() == Decimal("25.50")

    def test_daily_limit_when_zero_then_zero(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "0")
        assert daily_limit() == Decimal(0)

    @pytest.mark.parametrize("raw", ["ten", "-1", "nan", "inf", "$25"])
    def test_daily_limit_when_not_dollars_then_refused(self, monkeypatch, raw):
        monkeypatch.setenv(LIMIT_ENV, raw)
        with pytest.raises(ValueError, match=LIMIT_ENV):
            daily_limit()

    def test_validate_when_set_and_every_model_priced_then_starts(
        self, monkeypatch, priced_config, caplog
    ):
        monkeypatch.setenv(LIMIT_ENV, "25")
        with caplog.at_level(logging.INFO, logger=limit_mod.__name__):
            validate_ai_daily_limit_setting()
        assert f"{LIMIT_ENV}: 25 US dollars a day" in caplog.text

    def test_validate_when_unset_then_starts(self):
        validate_ai_daily_limit_setting()

    def test_validate_when_malformed_then_refuses_to_start(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "lots")
        with pytest.raises(ValueError, match=LIMIT_ENV):
            validate_ai_daily_limit_setting()


# ---------------------------------------------------------------------------
# A model the limit cannot price stops start-up
# ---------------------------------------------------------------------------


class TestUnpricedModels:
    def test_validate_when_set_and_model_unpriced_then_refuses_naming_it(
        self, monkeypatch, unpriced_config
    ):
        monkeypatch.setenv(LIMIT_ENV, "25")
        with pytest.raises(ValueError) as refused:
            validate_ai_daily_limit_setting()
        message = str(refused.value)
        assert LIMIT_ENV in message
        assert "mystery-llm (supported_llms)" in message
        assert PRICES_FILE in message
        assert "nova-2-lite" not in message

    def test_validate_when_unset_and_model_unpriced_then_starts(self, unpriced_config):
        validate_ai_daily_limit_setting()

    def test_validate_when_zero_and_model_unpriced_then_refuses(
        self, monkeypatch, unpriced_config
    ):
        monkeypatch.setenv(LIMIT_ENV, "0")
        with pytest.raises(ValueError, match="mystery-llm"):
            validate_ai_daily_limit_setting()

    def test_validate_when_combo_names_model_by_provider_id_then_refuses(
        self, monkeypatch
    ):
        _use_config(
            monkeypatch,
            {"nova-2-lite": {"model": _NOVA_ID, "provider": "aws_bedrock"}},
            {"AWS Bedrock": {"assistant_model": {"model": _NOVA_ID}}},
        )
        monkeypatch.setenv(LIMIT_ENV, "25")
        with pytest.raises(ValueError) as refused:
            validate_ai_daily_limit_setting()
        assert f"{_NOVA_ID} (ui_model_combos.AWS Bedrock.assistant_model)" in str(
            refused.value
        )

    def test_configured_llm_names_when_keys_and_combo_stages_then_lists_where_set(
        self, monkeypatch
    ):
        _use_config(
            monkeypatch,
            {"nova-2-lite": {"model": _NOVA_ID}, "gpt-4.1-mini": {}},
            {
                "Mixed": {
                    "summarization_model": {"model": "nova-2-lite"},
                    "semantic_highlighting_model": "gpt-4.1-mini",
                    "reranker_model": "not-a-chat-model",
                }
            },
        )
        assert configured_llm_names() == {
            "nova-2-lite": [
                "supported_llms",
                "ui_model_combos.Mixed.summarization_model",
            ],
            "gpt-4.1-mini": [
                "supported_llms",
                "ui_model_combos.Mixed.semantic_highlighting_model",
            ],
        }


class TestSecondsUntilMidnight:
    def test_seconds_when_noon_then_twelve_hours(self):
        assert seconds_until_utc_midnight(NOON) == 12 * 3600

    def test_seconds_when_just_before_midnight_then_rounds_up(self):
        now = datetime(2026, 11, 24, 23, 59, 59, 500000, tzinfo=timezone.utc)
        assert seconds_until_utc_midnight(now) == 1

    def test_seconds_when_other_timezone_then_counts_to_utc_midnight(self):
        from datetime import timedelta

        new_york_7am = datetime(
            2026, 11, 24, 7, 0, tzinfo=timezone(timedelta(hours=-5))
        )  # 12:00 UTC
        assert seconds_until_utc_midnight(new_york_7am) == 12 * 3600


# ---------------------------------------------------------------------------
# The day's total
# ---------------------------------------------------------------------------


class TestDailySpend:
    @pytest.mark.asyncio
    async def test_add_when_cost_then_upserts_onto_the_days_row(self):
        session = _Session()
        await add_to_daily_spend(session, Decimal("0.012"), now=NOON)
        assert len(session.statements) == 1
        sql = _sql(session.statements[0])
        assert "INSERT INTO ai_daily_spend" in sql
        assert "ON CONFLICT ON CONSTRAINT uq_ai_daily_spend_day DO UPDATE" in sql
        assert "cost_usd = (ai_daily_spend.cost_usd + excluded.cost_usd)" in sql
        params = session.statements[0].compile(dialect=postgresql.dialect()).params
        assert params["day"] == date(2026, 11, 24)
        assert params["cost_usd"] == Decimal("0.012")

    @pytest.mark.asyncio
    async def test_add_when_free_then_writes_nothing(self):
        session = _Session()
        await add_to_daily_spend(session, Decimal(0), now=NOON)
        assert session.statements == []

    @pytest.mark.asyncio
    async def test_spent_on_when_row_then_its_total(self):
        session = _Session(spent=Decimal("3.5"))
        assert await spent_on(session, date(2026, 11, 24)) == Decimal("3.5")
        assert "FROM ai_daily_spend" in _sql(session.statements[0])

    @pytest.mark.asyncio
    async def test_spent_on_when_no_row_then_zero(self):
        assert await spent_on(_Session(spent=None), date(2026, 11, 24)) == 0


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


class TestCheckAiAllowance:
    @pytest.mark.asyncio
    async def test_check_when_no_limit_then_never_reads_the_total(self):
        factory = _Factory(spent=Decimal("999"))
        await check_ai_allowance(session_factory=factory, now=NOON)
        assert factory.opened == 0

    @pytest.mark.asyncio
    async def test_check_when_under_the_limit_then_allowed(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "10")
        await check_ai_allowance(session_factory=_Factory(Decimal("9.99")), now=NOON)

    @pytest.mark.asyncio
    async def test_check_when_at_the_limit_then_refused_until_midnight(
        self, monkeypatch
    ):
        monkeypatch.setenv(LIMIT_ENV, "10")
        with pytest.raises(AiDailyLimitReached) as caught:
            await check_ai_allowance(session_factory=_Factory(Decimal("10")), now=NOON)
        assert str(caught.value) == LIMIT_MESSAGE
        assert caught.value.retry_after_seconds == 12 * 3600

    @pytest.mark.asyncio
    async def test_check_when_limit_zero_then_ai_is_off(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "0")
        with pytest.raises(AiDailyLimitReached):
            await check_ai_allowance(session_factory=_Factory(None), now=NOON)

    @pytest.mark.asyncio
    async def test_check_within_cache_window_then_reads_the_total_once(
        self, monkeypatch
    ):
        monkeypatch.setenv(LIMIT_ENV, "10")
        factory, clock = _Factory(Decimal("1")), _Clock()
        await check_ai_allowance(session_factory=factory, now=NOON, clock=clock)
        clock.now += limit_mod.CACHE_SECONDS - 1
        await check_ai_allowance(session_factory=factory, now=NOON, clock=clock)
        assert factory.opened == 1

    @pytest.mark.asyncio
    async def test_check_after_cache_window_then_reads_the_new_total(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "10")
        factory, clock = _Factory(Decimal("1")), _Clock()
        await check_ai_allowance(session_factory=factory, now=NOON, clock=clock)
        factory.session.spent = Decimal("10")
        clock.now += limit_mod.CACHE_SECONDS
        with pytest.raises(AiDailyLimitReached):
            await check_ai_allowance(session_factory=factory, now=NOON, clock=clock)
        assert factory.opened == 2

    @pytest.mark.asyncio
    async def test_check_on_a_new_day_then_reads_that_days_total(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "10")
        factory, clock = _Factory(Decimal("10")), _Clock()
        with pytest.raises(AiDailyLimitReached):
            await check_ai_allowance(session_factory=factory, now=NOON, clock=clock)
        factory.session.spent = None
        next_day = datetime(2026, 11, 25, 0, 0, 5, tzinfo=timezone.utc)
        await check_ai_allowance(session_factory=factory, now=next_day, clock=clock)
        assert factory.opened == 2

    @pytest.mark.asyncio
    async def test_check_when_refused_then_logs_once_a_day(self, monkeypatch, caplog):
        monkeypatch.setenv(LIMIT_ENV, "10")
        factory = _Factory(Decimal("12.5"))
        with caplog.at_level(logging.WARNING, logger=limit_mod.__name__):
            for _ in range(3):
                with pytest.raises(AiDailyLimitReached):
                    await check_ai_allowance(session_factory=factory, now=NOON)
        lines = [r.getMessage() for r in caplog.records]
        assert len(lines) == 1
        assert lines[0].startswith(LIMIT_REACHED_LOG)
        assert "12.5" in lines[0] and "10" in lines[0]


# ---------------------------------------------------------------------------
# HTTP: the dependency and the 429 answer
# ---------------------------------------------------------------------------


def _app_with_guarded_route() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AiDailyLimitReached, ai_daily_limit_handler)

    @app.post("/ai", dependencies=[Depends(require_ai_allowance)])
    async def _ai():
        return {"answer": "ok"}

    return app


class TestHttp:
    def test_route_when_limit_reached_then_429_with_message_and_retry_after(
        self, monkeypatch
    ):
        monkeypatch.setenv(LIMIT_ENV, "1")
        factory = _Factory(Decimal("1"))
        monkeypatch.setattr("ui.backend.auth.db.async_session_factory", factory)
        response = TestClient(_app_with_guarded_route()).post("/ai")
        assert response.status_code == 429
        assert response.json() == {"detail": LIMIT_MESSAGE}
        assert 1 <= int(response.headers["Retry-After"]) <= 24 * 3600

    def test_route_when_under_limit_then_answers(self, monkeypatch):
        monkeypatch.setenv(LIMIT_ENV, "1")
        monkeypatch.setattr(
            "ui.backend.auth.db.async_session_factory", _Factory(Decimal("0.5"))
        )
        response = TestClient(_app_with_guarded_route()).post("/ai")
        assert response.status_code == 200

    def test_handler_answers_the_registered_exception_only(self):
        exc = AiDailyLimitReached(60)
        response = asyncio.run(ai_daily_limit_handler(MagicMock(), exc))
        assert response.status_code == 429
        assert json.loads(response.body) == {"detail": LIMIT_MESSAGE}
        assert response.headers["Retry-After"] == "60"
        with pytest.raises(KeyError):
            asyncio.run(ai_daily_limit_handler(MagicMock(), KeyError("other")))


# ---------------------------------------------------------------------------
# Every route that calls an AI model is guarded
# ---------------------------------------------------------------------------


def _guarded_paths(router) -> set:
    return {
        route.path
        for route in router.routes
        if isinstance(route, APIRoute)
        and any(
            dep.call is require_ai_allowance for dep in route.dependant.dependencies
        )
    }


class TestAiRoutesAreGuarded:
    def test_search_summary_routes_are_guarded(self):
        from ui.backend.routes.summary import router

        assert {"/ai-summary/stream", "/ai-summary"} <= _guarded_paths(router)

    def test_assistant_route_is_guarded(self):
        from ui.backend.routes.assistant import router

        assert "/assistant/chat/stream" in _guarded_paths(router)

    def test_brief_routes_are_guarded(self):
        from ui.backend.routes.brief import router

        assert {"/brief/outline", "/brief/revise"} <= _guarded_paths(router)

    def test_document_summary_route_is_guarded(self):
        from ui.backend.routes.document_summary import router

        assert any(p.endswith("/{doc_id}/generate") for p in _guarded_paths(router))

    def test_admin_test_runs_are_guarded(self):
        from ui.backend.routes.testing import router

        guarded = _guarded_paths(router)
        assert any(p.endswith("/experiments/{experiment_id}/run") for p in guarded)
        assert any(p.endswith("/brief-checks") for p in guarded)

    def test_main_app_answers_the_limit_with_429(self):
        from ui.backend import main as main_module

        assert (
            main_module.app.exception_handlers[AiDailyLimitReached]
            is ai_daily_limit_handler
        )


# ---------------------------------------------------------------------------
# Calls without an activity id still count towards the day
# ---------------------------------------------------------------------------

_USAGE = {"llm_model": "nova-2-lite", "prompt_tokens": 1000, "completion_tokens": 500}
# 1000 * 0.00033/1k + 500 * 0.00275/1k
_USAGE_COST = Decimal("0.001705")


class TestCallsWithoutAnActivityId:
    @pytest.mark.asyncio
    async def test_record_daily_spend_adds_the_cost_and_no_activity_row(self):
        from ui.backend.services.usage_recorder import record_daily_spend

        factory = _Factory()
        assert await record_daily_spend(usage=_USAGE, session_factory=factory)
        (stmt,) = factory.session.statements
        compiled = stmt.compile(dialect=postgresql.dialect())
        assert "INSERT INTO ai_daily_spend" in str(compiled)
        assert compiled.params["cost_usd"] == _USAGE_COST
        assert factory.session.committed

    @pytest.mark.asyncio
    async def test_record_daily_spend_when_model_unpriced_then_nothing(self):
        from ui.backend.services.usage_recorder import record_daily_spend

        factory = _Factory()
        usage = {"llm_model": "qwen2.5-7b-instruct", "prompt_tokens": 50}
        assert not await record_daily_spend(usage=usage, session_factory=factory)
        assert factory.opened == 0

    def test_search_summary_without_search_id_then_counted_in_the_day(
        self, monkeypatch
    ):
        from ui.backend.routes import summary
        from ui.backend.schemas import AISummaryRequest

        daily, rows = [], []
        monkeypatch.setattr(
            summary, "schedule_daily_spend_recording", lambda **k: daily.append(k)
        )
        monkeypatch.setattr(
            summary, "schedule_llm_usage_recording", lambda **k: rows.append(k)
        )
        body = AISummaryRequest(query="q", results=[])
        summary._record_summary_usage(_USAGE, body, None)
        assert daily == [{"usage": _USAGE}]
        assert rows == []

    def test_assistant_turn_without_activity_id_then_counted_in_the_day(
        self, monkeypatch
    ):
        from ui.backend.auth.schemas import AssistantChatRequest
        from ui.backend.routes import assistant

        daily, rows = [], []
        monkeypatch.setattr(
            assistant, "schedule_daily_spend_recording", lambda **k: daily.append(k)
        )
        monkeypatch.setattr(
            assistant, "schedule_llm_usage_recording", lambda **k: rows.append(k)
        )
        body = AssistantChatRequest(query="q")
        assistant._record_assistant_usage({"usage": _USAGE}, body, None)
        assert daily == [{"usage": _USAGE}]
        assert rows == []

    def test_assistant_turn_with_activity_id_then_recorded_on_its_row(
        self, monkeypatch
    ):
        from ui.backend.auth.schemas import AssistantChatRequest
        from ui.backend.routes import assistant

        daily, rows = [], []
        monkeypatch.setattr(
            assistant, "schedule_daily_spend_recording", lambda **k: daily.append(k)
        )
        monkeypatch.setattr(
            assistant, "schedule_llm_usage_recording", lambda **k: rows.append(k)
        )
        body = AssistantChatRequest(query="q", activity_id="act-1")
        assistant._record_assistant_usage({"usage": _USAGE}, body, None)
        assert daily == []
        assert rows[0]["search_id"] == "act-1"


# ---------------------------------------------------------------------------
# A malformed limit stops the MCP/A2A server at start-up
# ---------------------------------------------------------------------------


class TestMcpStartup:
    @pytest.mark.asyncio
    async def test_mcp_startup_when_limit_malformed_then_fails(self, monkeypatch):
        from mcp_server.http_server import MCPApp

        monkeypatch.setenv(LIMIT_ENV, "ten")
        sent = []

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(message):
            sent.append(message)

        await MCPApp()({"type": "lifespan"}, receive, send)
        assert sent[0]["type"] == "lifespan.startup.failed"
        assert LIMIT_ENV in sent[0]["message"]

    @pytest.mark.asyncio
    async def test_mcp_startup_when_limit_set_and_model_unpriced_then_fails(
        self, monkeypatch, unpriced_config
    ):
        from mcp_server.http_server import MCPApp

        monkeypatch.setenv(LIMIT_ENV, "25")
        sent = []

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(message):
            sent.append(message)

        await MCPApp()({"type": "lifespan"}, receive, send)
        assert sent[0]["type"] == "lifespan.startup.failed"
        assert "mystery-llm (supported_llms)" in sent[0]["message"]
