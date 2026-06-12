"""Regression tests for the summarizer's HuggingFace token requirement.

The summarizer previously demanded ``HUGGINGFACE_API_KEY`` unconditionally at
setup, even though the token is only relevant to the HuggingFace provider. That
blocked the demo's default Azure Foundry provider (and Google Vertex) for any
user supplying only their provider's own credentials. The requirement must be
scoped to ``provider == "huggingface"``.
"""

from unittest.mock import MagicMock

import pytest

from pipeline.processors.summarization.summarizer import SummarizeProcessor


def _make_processor(provider: str) -> SummarizeProcessor:
    # An unknown model key routes through the backward-compat branch, so the
    # provider is taken verbatim from config — letting us pin it deterministically.
    return SummarizeProcessor(
        config={
            "llm_model": {"model": "unit-test-model", "provider": provider},
            "dense_model": "azure_small",
        }
    )


@pytest.mark.unit
def test_setup_does_not_require_hf_token_for_azure(monkeypatch):
    """Azure provider must set up without any HuggingFace token present."""
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    processor = _make_processor("azure_foundry")
    embedding_service = MagicMock()
    embedding_service.get_model.return_value = MagicMock()

    processor.setup(embedding_service=embedding_service)  # must not raise

    assert processor.provider == "azure_foundry"


@pytest.mark.unit
def test_setup_requires_hf_token_for_huggingface(monkeypatch):
    """HuggingFace provider still fails fast when no token is configured."""
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    processor = _make_processor("huggingface")
    embedding_service = MagicMock()
    embedding_service.get_model.return_value = MagicMock()

    with pytest.raises(ValueError, match="HUGGINGFACE_API_KEY"):
        processor.setup(embedding_service=embedding_service)


@pytest.mark.unit
def test_setup_uses_hf_token_for_huggingface_when_present(monkeypatch):
    """HuggingFace provider sets up cleanly once a token is available."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_unit_test_token")

    processor = _make_processor("huggingface")
    embedding_service = MagicMock()
    embedding_service.get_model.return_value = MagicMock()

    processor.setup(embedding_service=embedding_service)  # must not raise

    assert processor._hf_token == "hf_unit_test_token"
