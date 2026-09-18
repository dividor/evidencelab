"""End-to-end validation that admin-displayed tokens and cost match reality.

These tests drive the **real** backend code paths used by the AI summary
and Research Assistant flows. They do not call a live LLM — instead the
``UsageMetadataCallbackHandler`` is replaced with a stand-in pre-populated
with a deterministic provider payload, simulating the moment LangChain
would have collected real usage events.

What they prove

1. **No drift in the chain.** The exact ``input_tokens`` / ``output_tokens``
   numbers a provider would report are the exact numbers persisted to
   ``user_activity.prompt_tokens`` / ``completion_tokens`` (and therefore
   the exact values rendered in the admin "Tokens" column).
2. **Cost matches the rate table.** ``cost_usd`` persisted to the DB is
   exactly ``(prompt * input_rate + completion * output_rate) / 1000``,
   quantised to micro-dollar precision, using the published rate from
   ``LLM_COSTS_PER_1K``. No fudge factor, no rounding mismatch.
3. **The assistant flow surfaces the same shape.** ``_build_done_event``
   on the assistant path emits the same ``usage`` payload that the
   activity-log POST persists.

Running against a real LLM (manual smoke test, requires API keys) is a
separate concern and lives in ``scripts/quality/verify_token_usage.py``.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch
from uuid import uuid4

import pytest

import ui.backend.services.assistant_service as assistant_service
import ui.backend.services.llm_service as llm_service
from ui.backend.auth.schemas import ActivitySummaryUpdateAnonymous
from ui.backend.routes.activity import _apply_token_usage
from ui.backend.utils.llm_costs import LLM_COSTS_PER_1K, compute_cost

# ---------------------------------------------------------------------------
# Fakes that look enough like LangChain to drive the real service code
# ---------------------------------------------------------------------------


def _make_fake_handler(usage_metadata: Dict[str, Dict[str, int]]):
    """Build a stand-in for ``UsageMetadataCallbackHandler``.

    Real handlers populate ``.usage_metadata`` after the LLM stream
    completes. The test simulates that result up-front; the production
    code reads the attribute identically either way.
    """

    class FakeHandler:
        def __init__(self, *_args, **_kwargs):
            self.usage_metadata = usage_metadata

    return FakeHandler


class _FakeStreamingLLM:
    """Minimal LangChain-shaped chat model for streaming calls."""

    async def astream(self, _messages, config=None):
        for token in ("Hello ", "world"):
            yield SimpleNamespace(content=token)


class _FakeInvokingLLM:
    """Minimal LangChain-shaped chat model for ainvoke calls."""

    async def ainvoke(self, _messages, config=None):
        return SimpleNamespace(content="  generated summary  ")


def _make_activity_stub():
    """Build a stand-in for the ``UserActivity`` ORM object."""
    return SimpleNamespace(
        id=uuid4(),
        llm_model=None,
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
    )


def _expected_cost(model_key: str, prompt: int, completion: int) -> Decimal:
    """Compute the published-rate cost the DB row should match."""
    input_rate, output_rate = LLM_COSTS_PER_1K[model_key]
    raw = (Decimal(prompt) * input_rate + Decimal(completion) * output_rate) / Decimal(
        1000
    )
    return raw.quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------
# AI summary streaming end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestStreamAiSummaryEndToEnd:
    """Drive ``stream_ai_summary`` and validate the persisted activity row."""

    async def _drive(
        self,
        monkeypatch,
        model_key: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Dict[str, Any]:
        """Run the stream and return the final metadata dict yielded."""
        usage_metadata = {
            model_key: {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
            }
        }
        monkeypatch.setattr(
            llm_service,
            "UsageMetadataCallbackHandler",
            _make_fake_handler(usage_metadata),
        )
        monkeypatch.setattr(
            llm_service,
            "get_llm",
            lambda model=None, temperature=None, max_tokens=None: _FakeStreamingLLM(),
        )

        final_metadata: Dict[str, Any] = {}
        async for item in llm_service.stream_ai_summary(
            "query", [{"text": "a"}], model_key=model_key
        ):
            if isinstance(item, dict):
                final_metadata = item
        return final_metadata

    async def test_known_model_persists_exact_tokens_and_published_rate_cost(
        self, monkeypatch
    ):
        """Provider numbers and published-rate cost flow through unchanged."""
        prompt_tokens, completion_tokens = 1234, 567
        model_key = "gpt-4.1-mini"

        metadata = await self._drive(
            monkeypatch, model_key, prompt_tokens, completion_tokens
        )

        # 1. SSE metadata exposes the provider's exact numbers.
        assert metadata["llm_model"] == model_key
        assert metadata["prompt_tokens"] == prompt_tokens
        assert metadata["completion_tokens"] == completion_tokens

        # 2. When the frontend forwards them via PATCH, the activity row
        #    ends up with those exact tokens and the published-rate cost.
        body = ActivitySummaryUpdateAnonymous(**metadata)
        activity = _make_activity_stub()
        _apply_token_usage(activity, body)

        assert activity.prompt_tokens == prompt_tokens
        assert activity.completion_tokens == completion_tokens
        assert activity.llm_model == model_key
        assert activity.cost_usd == _expected_cost(
            model_key, prompt_tokens, completion_tokens
        )

    async def test_unknown_model_keeps_tokens_drops_cost(self, monkeypatch):
        """For models we have no rate for, tokens still persist; cost is None."""
        model_key = "custom-model-not-in-table"
        prompt_tokens, completion_tokens = 800, 200

        metadata = await self._drive(
            monkeypatch, model_key, prompt_tokens, completion_tokens
        )

        body = ActivitySummaryUpdateAnonymous(**metadata)
        activity = _make_activity_stub()
        _apply_token_usage(activity, body)

        assert activity.prompt_tokens == prompt_tokens
        assert activity.completion_tokens == completion_tokens
        assert activity.cost_usd is None  # no rate, no fabricated value

    @pytest.mark.parametrize("model_key", sorted(LLM_COSTS_PER_1K.keys()))
    async def test_every_known_model_uses_its_own_rate(self, monkeypatch, model_key):
        """For every priced model, the DB cost == its rate-derived value."""
        prompt_tokens, completion_tokens = 1000, 500

        metadata = await self._drive(
            monkeypatch, model_key, prompt_tokens, completion_tokens
        )

        body = ActivitySummaryUpdateAnonymous(**metadata)
        activity = _make_activity_stub()
        _apply_token_usage(activity, body)

        expected = _expected_cost(model_key, prompt_tokens, completion_tokens)
        assert activity.cost_usd == expected
        # Sanity: cross-check independent recomputation.
        assert activity.cost_usd == compute_cost(
            model_key, prompt_tokens, completion_tokens
        )


# ---------------------------------------------------------------------------
# AI summary non-streaming end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGenerateAiSummaryEndToEnd:
    """Same guarantees for the non-streaming ``generate_ai_summary_with_usage``."""

    async def test_invoke_round_trip_matches_rate_table(self, monkeypatch):
        model_key = "gemini-2.5-flash"
        prompt_tokens, completion_tokens = 600, 250

        usage_metadata = {
            model_key: {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
            }
        }
        monkeypatch.setattr(
            llm_service,
            "UsageMetadataCallbackHandler",
            _make_fake_handler(usage_metadata),
        )
        monkeypatch.setattr(
            llm_service,
            "get_llm",
            lambda model=None, temperature=None, max_tokens=None: _FakeInvokingLLM(),
        )

        summary, usage = await llm_service.generate_ai_summary_with_usage(
            "query", [{"text": "a"}], model_key=model_key
        )

        # Content stripping unchanged from the previous behaviour.
        assert summary == "generated summary"

        # Usage payload matches the provider's exact numbers.
        assert usage == {
            "llm_model": model_key,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

        # And the DB row would carry the published-rate cost.
        body = ActivitySummaryUpdateAnonymous(**usage)
        activity = _make_activity_stub()
        _apply_token_usage(activity, body)
        assert activity.cost_usd == _expected_cost(
            model_key, prompt_tokens, completion_tokens
        )


# ---------------------------------------------------------------------------
# Research Assistant done event end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssistantDoneEventEndToEnd:
    """The assistant emits the same usage shape used by the AI summary path.

    We exercise ``_build_done_event`` directly because the surrounding
    LangGraph agent is out of scope for unit-level fakes — but every
    piece downstream of the callback handler (the cost computation, the
    payload key names) is the same code as the AI summary path covered
    above. This test just confirms the assistant glues into that chain.
    """

    def test_done_event_carries_provider_numbers_and_persists_cost(self):
        model_key = "gpt-4.1-mini"
        prompt_tokens, completion_tokens = 4321, 1234

        handler = SimpleNamespace(
            usage_metadata={
                model_key: {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                }
            }
        )

        event = assistant_service._build_done_event(
            uuid4(), usage_handler=handler, model_key=model_key
        )

        assert event["type"] == "done"
        assert event["usage"] == {
            "llm_model": model_key,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

        # And the matching activity-log POST would store the right cost.
        # (The assistant uses POST /activity/, not PATCH, but the same
        # _resolve_cost path runs on the server.)
        from ui.backend.routes.activity import _resolve_cost

        recomputed = _resolve_cost(
            None,
            event["usage"]["llm_model"],
            event["usage"]["prompt_tokens"],
            event["usage"]["completion_tokens"],
        )
        assert recomputed == _expected_cost(model_key, prompt_tokens, completion_tokens)

    def test_done_event_carries_trace_url_under_both_keys(self):
        """``trace_url`` is the vendor-neutral key; ``langsmith_trace_url``
        rides along for one release so older bundles keep working."""
        handler = SimpleNamespace(usage_metadata={})
        with patch.object(
            assistant_service, "_get_trace_url", return_value="https://t.example/r/1"
        ):
            event = assistant_service._build_done_event(
                uuid4(), usage_handler=handler, model_key="gpt-4.1-mini"
            )
        assert event["trace_url"] == "https://t.example/r/1"
        assert event["langsmith_trace_url"] == "https://t.example/r/1"

    def test_done_event_without_tracing_has_no_trace_keys(self):
        handler = SimpleNamespace(usage_metadata={})
        with patch.object(assistant_service, "_get_trace_url", return_value=None):
            event = assistant_service._build_done_event(
                uuid4(), usage_handler=handler, model_key="gpt-4.1-mini"
            )
        assert "trace_url" not in event
        assert "langsmith_trace_url" not in event

    def test_done_event_with_no_usage_omits_payload(self):
        """A handler with no provider data should not synthesize one."""
        handler = SimpleNamespace(usage_metadata={})
        event = assistant_service._build_done_event(
            uuid4(), usage_handler=handler, model_key="gpt-4.1-mini"
        )
        # Just the model key landed — no token counts to invent.
        assert event["usage"] == {"llm_model": "gpt-4.1-mini"}
