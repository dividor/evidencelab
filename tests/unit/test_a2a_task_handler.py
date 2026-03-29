"""Unit tests for A2A task handler."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from a2a_server.schemas import Message, TaskState, TextPart


class TestExtractQuery:
    def test_extracts_text(self):
        from a2a_server.task_handler import _extract_query

        msg = Message(role="user", parts=[TextPart(text="What are findings?")])
        assert _extract_query(msg) == "What are findings?"

    def test_strips_whitespace(self):
        from a2a_server.task_handler import _extract_query

        msg = Message(role="user", parts=[TextPart(text="  query  ")])
        assert _extract_query(msg) == "query"

    def test_no_text_raises(self):
        from a2a_server.task_handler import _extract_query

        msg = Message(role="user", parts=[TextPart(text="")])
        with pytest.raises(ValueError, match="No text content"):
            _extract_query(msg)


class TestExtractSkill:
    def test_defaults_to_research(self):
        from a2a_server.task_handler import _extract_skill

        msg = Message(role="user", parts=[TextPart(text="What are findings?")])
        assert _extract_skill(msg) == "research"

    def test_search_prefix_returns_search(self):
        from a2a_server.task_handler import _extract_skill

        msg = Message(role="user", parts=[TextPart(text="Search for WASH findings")])
        assert _extract_skill(msg) == "search"

    def test_metadata_skill_overrides(self):
        from a2a_server.task_handler import _extract_skill

        msg = Message(
            role="user",
            parts=[TextPart(text="Some query")],
            metadata={"skill": "search"},
        )
        assert _extract_skill(msg) == "search"


@pytest.mark.asyncio
async def test_handle_task_research(monkeypatch):
    """handle_task calls mcp_ask_assistant for research skill."""
    from mcp_server.schemas import MCPAssistantResponse

    fake_response = MCPAssistantResponse(
        answer="The findings show...",
        sources=[],
        citations=[],
        references=[],
        citation_guidance="",
        query="What are findings?",
        data_source="uneg",
    )

    mock_ask = AsyncMock(return_value=fake_response)

    assistant_mod = ModuleType("mcp_server.tools.assistant")
    assistant_mod.mcp_ask_assistant = mock_ask
    monkeypatch.setitem(sys.modules, "mcp_server.tools.assistant", assistant_mod)

    from a2a_server.task_handler import handle_task

    msg = Message(role="user", parts=[TextPart(text="What are findings?")])
    task = await handle_task("task-1", msg)

    assert task.id == "task-1"
    assert task.status.state == TaskState.COMPLETED
    assert task.artifacts is not None
    assert len(task.artifacts) >= 1
    text_part = task.artifacts[0].parts[0]
    assert hasattr(text_part, "text")
    assert "findings" in text_part.text.lower()


@pytest.mark.asyncio
async def test_handle_task_research_includes_citations(monkeypatch):
    """Research skill artifact contains text answer AND citation data part."""
    from mcp_server.schemas import MCPAssistantResponse, MCPCitation

    fake_citation = MCPCitation(
        label="[1]",
        url="https://evidencelab.ai/document/doc-123",
        title="UNDP Evaluation 2023",
        organization="UNDP",
        year="2023",
    )
    fake_response = MCPAssistantResponse(
        answer="Climate adaptation programs showed significant impact [[1]](url).",
        sources=[{"doc_id": "doc-123", "title": "UNDP Evaluation 2023"}],
        citations=[fake_citation],
        references=["[1] UNDP Evaluation 2023 (UNDP, 2023)"],
        citation_guidance="",
        query="What are climate findings?",
        data_source="uneg",
    )

    mock_ask = AsyncMock(return_value=fake_response)
    assistant_mod = ModuleType("mcp_server.tools.assistant")
    assistant_mod.mcp_ask_assistant = mock_ask
    monkeypatch.setitem(sys.modules, "mcp_server.tools.assistant", assistant_mod)

    from a2a_server.schemas import DataPart
    from a2a_server.task_handler import handle_task

    msg = Message(
        role="user",
        parts=[TextPart(text="What are climate findings?")],
        metadata={"data_source": "uneg"},
    )
    task = await handle_task("task-cit", msg)

    assert task.status.state == TaskState.COMPLETED
    assert task.artifacts is not None
    artifact = task.artifacts[0]

    # First part is the text answer
    text_part = artifact.parts[0]
    assert isinstance(text_part, TextPart)
    assert "Climate adaptation" in text_part.text

    # Second part is the structured citation data
    assert len(artifact.parts) == 2
    data_part = artifact.parts[1]
    assert isinstance(data_part, DataPart)
    assert "citations" in data_part.data
    assert len(data_part.data["citations"]) == 1
    assert data_part.data["citations"][0]["label"] == "[1]"
    assert data_part.data["citations"][0]["organization"] == "UNDP"
    assert "references" in data_part.data
    assert len(data_part.data["references"]) == 1
    assert "sources" in data_part.data
    assert len(data_part.data["sources"]) == 1


@pytest.mark.asyncio
async def test_handle_task_failure(monkeypatch):
    """handle_task returns FAILED state when the assistant raises."""
    mock_ask = AsyncMock(side_effect=RuntimeError("boom"))

    assistant_mod = ModuleType("mcp_server.tools.assistant")
    assistant_mod.mcp_ask_assistant = mock_ask
    monkeypatch.setitem(sys.modules, "mcp_server.tools.assistant", assistant_mod)

    from a2a_server.task_handler import handle_task

    msg = Message(role="user", parts=[TextPart(text="failing query")])
    task = await handle_task("task-err", msg)

    assert task.status.state == TaskState.FAILED
    assert task.artifacts is None


@pytest.mark.asyncio
async def test_handle_task_search(monkeypatch):
    """handle_task calls mcp_search for search skill."""
    from mcp_server.schemas import MCPSearchResponse

    fake_response = MCPSearchResponse(
        total=0,
        query="Search for WASH",
        summary="0 results",
        results=[],
        citations=[],
        references=[],
        citation_guidance="",
        data_source="uneg",
    )

    mock_search = AsyncMock(return_value=fake_response)

    search_mod = ModuleType("mcp_server.tools.search")
    search_mod.mcp_search = mock_search
    monkeypatch.setitem(sys.modules, "mcp_server.tools.search", search_mod)

    from a2a_server.task_handler import handle_task

    msg = Message(role="user", parts=[TextPart(text="Search for WASH findings")])
    task = await handle_task("task-search", msg)

    assert task.status.state == TaskState.COMPLETED
    assert task.artifacts is not None
    mock_search.assert_called_once()
