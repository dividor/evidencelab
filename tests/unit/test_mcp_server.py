"""Unit tests for MCP server tool functions."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_server.schemas import (
    MCPAssistantResponse,
    MCPDocumentResponse,
    MCPSearchResponse,
)

# ── Search tool tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_tool_basic(monkeypatch):
    """mcp_search returns an MCPSearchResponse for a basic query."""
    hit = SimpleNamespace(
        id="chunk-1",
        score=0.85,
        payload={
            "doc_id": "doc-1",
            "sys_text": "Climate change impacts on agriculture.",
            "sys_page_num": 5,
            "sys_headings": ["Introduction"],
            "tag_section_type": "findings",
        },
    )

    def fake_search_chunks(**kwargs):
        return [hit]

    fake_db = MagicMock()
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {
        "doc-1": {
            "map_title": "Climate Report",
            "map_organization": "UNEP",
            "map_published_year": "2023",
        }
    }
    fake_pg.fetch_chunks.return_value = {}

    from ui.backend.schemas import SearchResult as BackendSearchResult

    fake_search_result = BackendSearchResult(
        chunk_id="chunk-1",
        doc_id="doc-1",
        text="Climate change impacts on agriculture.",
        page_num=5,
        headings=["Introduction"],
        section_type="findings",
        score=0.85,
        title="Climate Report",
        organization="UNEP",
        year="2023",
        metadata={"report_url": "https://example.com/report.pdf"},
    )

    # Patch the source modules that are lazily imported inside mcp_search
    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    app_state_mod.logger = MagicMock()
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    routes_search_mod = ModuleType("ui.backend.routes.search")
    routes_search_mod._build_doc_cache = lambda pg, results: {}
    routes_search_mod._build_chunk_cache = lambda pg, results: {}
    routes_search_mod._build_search_results = lambda *args, **kwargs: [
        fake_search_result
    ]
    monkeypatch.setitem(sys.modules, "ui.backend.routes.search", routes_search_mod)

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(query="climate change")

    assert isinstance(result, MCPSearchResponse)
    assert result.total == 1
    assert result.query == "climate change"
    assert result.results[0].doc_id == "doc-1"
    assert result.results[0].title == "Climate Report"
    assert result.results[0].score == 0.85


@pytest.mark.asyncio
async def test_search_tool_with_filters(monkeypatch):
    """Filters dict is forwarded to search_chunks."""
    captured_kwargs: dict = {}

    def fake_search_chunks(**kwargs):
        captured_kwargs.update(kwargs)
        return []

    fake_db = MagicMock()

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.search import mcp_search

    filters = {"organization": "UNICEF", "published_year": "2022"}
    result = await mcp_search(
        query="water sanitation",
        filters=filters,
        limit=5,
    )

    assert isinstance(result, MCPSearchResponse)
    assert result.total == 0
    assert captured_kwargs["filters"] == filters
    assert captured_kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_search_tool_empty_results(monkeypatch):
    """Empty search results return an empty list, not an error."""

    def fake_search_chunks(**kwargs):
        return []

    fake_db = MagicMock()

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(query="nonexistent topic xyz")

    assert isinstance(result, MCPSearchResponse)
    assert result.total == 0
    assert result.results == []


# ── Document tool tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_document_found(monkeypatch):
    """mcp_get_document returns MCPDocumentResponse when the doc exists."""
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {
        "doc-42": {
            "map_title": "Education Evaluation",
            "map_organization": "UNICEF",
            "map_published_year": "2021",
            "sys_full_summary": "A comprehensive evaluation of education programs.",
            "sys_data": {"abstract": "Education matters."},
        }
    }

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.document import mcp_get_document

    result = await mcp_get_document(doc_id="doc-42")

    assert isinstance(result, MCPDocumentResponse)
    assert result.doc_id == "doc-42"
    assert result.title == "Education Evaluation"
    assert result.organization == "UNICEF"
    assert result.year == "2021"
    assert result.summary == "A comprehensive evaluation of education programs."
    assert result.abstract == "Education matters."


@pytest.mark.asyncio
async def test_get_document_not_found(monkeypatch):
    """mcp_get_document raises ValueError when the doc does not exist."""
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.document import mcp_get_document

    with pytest.raises(ValueError, match="Document not found: missing-doc"):
        await mcp_get_document(doc_id="missing-doc")


# ── Assistant tool tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_assistant_basic(monkeypatch):
    """mcp_ask_assistant returns MCPAssistantResponse from a streamed response."""

    async def fake_stream(**kwargs):
        yield {"type": "token", "token": "The answer is 42."}
        yield {
            "type": "sources",
            "sources": [{"doc_id": "doc-1", "title": "Guide"}],
        }

    assistant_svc_mod = ModuleType("ui.backend.services.assistant_service")
    assistant_svc_mod.stream_research_response = fake_stream
    monkeypatch.setitem(
        sys.modules, "ui.backend.services.assistant_service", assistant_svc_mod
    )

    from mcp_server.tools.assistant import mcp_ask_assistant

    result = await mcp_ask_assistant(query="What is the meaning of life?")

    assert isinstance(result, MCPAssistantResponse)
    assert result.answer == "The answer is 42."
    assert result.query == "What is the meaning of life?"
    assert len(result.sources) == 1
    assert result.sources[0]["doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_ask_assistant_timeout(monkeypatch):
    """mcp_ask_assistant raises RuntimeError on timeout with no partial answer."""
    import mcp_server.tools.assistant as assistant_mod

    # Use a very short timeout for the test
    monkeypatch.setattr(assistant_mod, "_ASSISTANT_TIMEOUT_SECONDS", 0.05)

    async def fake_stream(**kwargs):
        # Never yield a token, just hang
        await asyncio.sleep(10)
        # This line is needed so Python sees this as an async generator
        yield {"type": "token", "token": "never reached"}  # pragma: no cover

    assistant_svc_mod = ModuleType("ui.backend.services.assistant_service")
    assistant_svc_mod.stream_research_response = fake_stream
    monkeypatch.setitem(
        sys.modules, "ui.backend.services.assistant_service", assistant_svc_mod
    )

    from mcp_server.tools.assistant import mcp_ask_assistant

    with pytest.raises(RuntimeError, match="Assistant timed out"):
        await mcp_ask_assistant(query="slow question")
