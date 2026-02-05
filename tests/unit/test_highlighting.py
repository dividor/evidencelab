"""
Unit tests for the unified highlighting API endpoint.
Tests keyword and semantic highlighting functionality using the FastAPI handler.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ui.backend import main as main_module

SAMPLE_TEXT = (
    "The Ministry of Health leads reforms. " "Other ministries support health efforts."
)


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "")
    main_module.app.highlight_cache = {}


@pytest.mark.asyncio
async def test_keyword_highlighting_exact_phrase():
    request = main_module.UnifiedHighlightRequest(
        query="Ministry of Health",
        text=SAMPLE_TEXT,
        highlight_type="keyword",
    )

    data = (await main_module.highlight_text(request)).model_dump()
    assert "keyword" in data["types_returned"]
    assert any(m["match_type"] == "exact_phrase" for m in data["matches"])
    assert "<em>" in data["highlighted_text"]


@pytest.mark.asyncio
async def test_keyword_highlighting_word_matches():
    request = main_module.UnifiedHighlightRequest(
        query="health ministries",
        text=SAMPLE_TEXT,
        highlight_type="keyword",
    )

    data = (await main_module.highlight_text(request)).model_dump()
    assert "keyword" in data["types_returned"]
    assert any(m["match_type"] == "word" for m in data["matches"])


@pytest.mark.asyncio
async def test_semantic_highlighting_with_mocked_llm():
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(
        side_effect=[
            SimpleNamespace(content='["Ministry of Health"]'),
            SimpleNamespace(content='["Ministry of Health"]'),
        ]
    )

    with patch("utils.llm_factory.get_llm", return_value=mock_llm):
        request = main_module.UnifiedHighlightRequest(
            query="health ministries",
            text=SAMPLE_TEXT,
            highlight_type="semantic",
        )
        data = (await main_module.highlight_text(request)).model_dump()

    assert "semantic" in data["types_returned"]
    assert any(m["match_type"] == "semantic" for m in data["matches"])


@pytest.mark.asyncio
async def test_both_highlighting_types():
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(
        side_effect=[
            SimpleNamespace(content='["Ministry of Health"]'),
            SimpleNamespace(content='["Ministry of Health"]'),
        ]
    )

    with patch("utils.llm_factory.get_llm", return_value=mock_llm):
        request = main_module.UnifiedHighlightRequest(
            query="health ministries",
            text=SAMPLE_TEXT,
            highlight_type="both",
        )
        data = (await main_module.highlight_text(request)).model_dump()

    assert "keyword" in data["types_returned"]
    assert "semantic" in data["types_returned"]
    assert data["highlighted_text"].count("<em>") == data["highlighted_text"].count(
        "</em>"
    )


@pytest.mark.asyncio
async def test_highlighting_invalid_type():
    request = main_module.UnifiedHighlightRequest(
        query="health",
        text=SAMPLE_TEXT,
        highlight_type="invalid",
    )

    with pytest.raises(main_module.HTTPException) as exc:
        await main_module.highlight_text(request)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_highlighting_empty_query():
    request = main_module.UnifiedHighlightRequest(
        query="",
        text=SAMPLE_TEXT,
        highlight_type="both",
    )

    data = (await main_module.highlight_text(request)).model_dump()
    assert data["total"] == 0
    assert data["matches"] == []
