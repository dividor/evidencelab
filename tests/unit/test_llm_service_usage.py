"""Tests for ``summarize_usage_metadata`` in the LLM service layer.

Uses an in-process stand-in for ``UsageMetadataCallbackHandler`` so the
test runs without a live LangChain provider — we only care about the
shape we surface to the route layer.
"""

from types import SimpleNamespace

import pytest

from pipeline.db import config as db_config
from ui.backend.services.llm_service import summarize_usage_metadata
from ui.backend.services.usage_recorder import usage_cost
from utils import llm_factory

_NOVA_ID = "us.amazon.nova-2-lite-v1:0"


def _handler(usage_metadata):
    """Build a fake handler exposing the ``usage_metadata`` attribute."""
    return SimpleNamespace(usage_metadata=usage_metadata)


@pytest.fixture
def nova_config(monkeypatch):
    """config.json lists Nova 2 Lite under its key; no default model is set."""
    monkeypatch.setattr(
        db_config,
        "SUPPORTED_LLMS",
        {"nova-2-lite": {"model": _NOVA_ID, "provider": "aws_bedrock"}},
    )
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(llm_factory, "_load_llm_config", lambda: {})


@pytest.mark.unit
class TestSummarizeUsageMetadata:
    """Shape of the dict passed back to the route layer."""

    def test_single_model_payload(self):
        """Standard case: provider reports one model with both token counts."""
        handler = _handler(
            {"gpt-4.1-mini": {"input_tokens": 1234, "output_tokens": 567}}
        )
        out = summarize_usage_metadata(handler, model_key="gpt-4.1-mini")
        assert out == {
            "llm_model": "gpt-4.1-mini",
            "prompt_tokens": 1234,
            "completion_tokens": 567,
        }

    def test_sums_across_multiple_models(self):
        """Agent that hit two models accumulates totals (single-model rate)."""
        handler = _handler(
            {
                "model-a": {"input_tokens": 100, "output_tokens": 50},
                "model-b": {"input_tokens": 25, "output_tokens": 10},
            }
        )
        out = summarize_usage_metadata(handler, model_key="model-a")
        assert out["prompt_tokens"] == 125
        assert out["completion_tokens"] == 60
        assert out["llm_model"] == "model-a"

    def test_empty_usage_returns_just_model(self):
        """No reported usage → only the model_key is surfaced."""
        handler = _handler({})
        out = summarize_usage_metadata(handler, model_key="gemini-2.5-flash")
        assert out == {"llm_model": "gemini-2.5-flash"}

    def test_missing_model_key_when_no_default_model_returns_only_tokens(
        self, nova_config
    ):
        """No model_key and no default model → still surface the tokens."""
        handler = _handler({"some-model": {"input_tokens": 10, "output_tokens": 5}})
        out = summarize_usage_metadata(handler, model_key=None)
        assert out == {"prompt_tokens": 10, "completion_tokens": 5}

    def test_summarize_when_named_by_provider_id_then_labelled_and_priced_by_key(
        self, nova_config
    ):
        """A request naming the provider's model id is priced as its key."""
        handler = _handler({_NOVA_ID: {"input_tokens": 1000, "output_tokens": 1000}})
        out = summarize_usage_metadata(handler, model_key=_NOVA_ID)
        assert out["llm_model"] == "nova-2-lite"
        assert str(usage_cost(out)) == "0.003080"

    def test_summarize_when_no_model_and_default_set_then_labelled_by_its_key(
        self, nova_config, monkeypatch
    ):
        """A request naming no model runs on the default one, and says so."""
        monkeypatch.setenv("LLM_MODEL", _NOVA_ID)
        handler = _handler({_NOVA_ID: {"input_tokens": 1000, "output_tokens": 1000}})
        out = summarize_usage_metadata(handler, model_key=None)
        assert out["llm_model"] == "nova-2-lite"
        assert str(usage_cost(out)) == "0.003080"

    def test_handler_with_no_usage_metadata_attribute(self):
        """Defensive: an object lacking the attribute returns an empty payload."""

        class Bare:
            pass

        out = summarize_usage_metadata(Bare(), model_key="gpt-4.1-mini")
        assert out == {"llm_model": "gpt-4.1-mini"}

    def test_zero_token_counts_omitted(self):
        """Zero counts are not emitted — keeps the payload tight."""
        handler = _handler({"m": {"input_tokens": 0, "output_tokens": 0}})
        out = summarize_usage_metadata(handler, model_key="m")
        assert "prompt_tokens" not in out
        assert "completion_tokens" not in out
        assert out["llm_model"] == "m"

    def test_missing_keys_treated_as_zero(self):
        """Some providers only fill one side; the other should not break us."""
        handler = _handler({"m": {"input_tokens": 7}})
        out = summarize_usage_metadata(handler, model_key="m")
        assert out["prompt_tokens"] == 7
        assert "completion_tokens" not in out
