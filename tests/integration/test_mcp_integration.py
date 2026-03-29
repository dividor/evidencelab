"""Integration tests for the MCP server.

These tests run inside Docker against the MCP server with real data
ingested by the pipeline. They verify end-to-end tool execution via
HTTP POST to the MCP endpoint.
"""

import json
import os

import pytest
import requests

MCP_URL = os.getenv("MCP_BASE_URL", "http://mcp:8001") + "/mcp"
API_KEY = os.getenv("API_SECRET_KEY", os.getenv("REACT_APP_API_KEY", ""))


def _mcp_call(method: str, params: dict | None = None, call_id: int = 1) -> dict:
    """Send a JSON-RPC call to the MCP server and return the result."""
    body = {"jsonrpc": "2.0", "method": method, "id": call_id}
    if params:
        body["params"] = params
    resp = requests.post(
        MCP_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-API-Key": API_KEY,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _tool_call(name: str, arguments: dict) -> dict:
    """Call an MCP tool and return the parsed text content."""
    data = _mcp_call("tools/call", {"name": name, "arguments": arguments})
    result = data.get("result", {})
    if isinstance(result, dict) and result.get("isError"):
        content = result.get("content", [{}])[0]
        pytest.fail(f"Tool error: {content.get('text', 'unknown')}")
    for item in result.get("content", []):
        if item.get("type") == "text":
            return json.loads(item["text"])
    pytest.fail("No text content in tool response")


class TestMCPIntegration:
    """MCP server integration tests using pipeline-ingested data."""

    def test_initialize(self):
        """MCP server responds to initialize."""
        data = _mcp_call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        )
        result = data["result"]
        assert result["serverInfo"]["name"] == "Evidence Lab"
        assert "tools" in result["capabilities"]

    def test_tools_list(self):
        """tools/list returns search and get_document tools."""
        data = _mcp_call("tools/list")
        tools = data["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "search" in names
        assert "get_document" in names
        assert "ask_assistant" not in names  # removed — use A2A for research

    def test_tools_have_descriptions(self):
        """All tools have non-empty descriptions."""
        data = _mcp_call("tools/list")
        for tool in data["result"]["tools"]:
            assert tool.get("description"), f"{tool['name']} missing description"
            assert (
                len(tool["description"]) > 50
            ), f"{tool['name']} description too short"

    def test_search_tool_returns_results(self):
        """Search returns results from ingested test data."""
        result = _tool_call("search", {"query": "health", "limit": 5})
        assert "total" in result
        assert "results" in result
        if result["total"] == 0:
            pytest.skip("No indexed documents — skipping result data assertions")
        first = result["results"][0]
        assert "text" in first
        assert "title" in first
        assert "score" in first
        assert first["score"] > 0

    def test_search_with_filters(self):
        """Search with filters returns filtered results."""
        result = _tool_call(
            "search",
            {
                "query": "evaluation",
                "filters": {"published_year": "2020"},
                "limit": 5,
            },
        )
        # Should not error — may return 0 results if no 2020 data
        assert "total" in result
        assert "results" in result

    def test_search_with_facets(self):
        """Search with include_facets returns facet data."""
        result = _tool_call(
            "search",
            {"query": "health", "limit": 1, "include_facets": True},
        )
        assert "facets" in result
        if not result["facets"]:
            pytest.skip("No indexed documents — skipping facet data assertions")
        # At least one facet should have values
        for field, values in result["facets"].items():
            if values:
                assert "value" in values[0]
                assert "count" in values[0]
                break

    def test_search_no_facets_by_default(self):
        """Search without include_facets returns no facets."""
        result = _tool_call("search", {"query": "health", "limit": 1})
        assert result.get("facets") is None

    def test_get_document(self):
        """get_document returns metadata for a known doc_id."""
        # First search to get a doc_id
        search_result = _tool_call("search", {"query": "health", "limit": 1})
        if search_result["total"] == 0:
            pytest.skip("No documents to test with")
        doc_id = search_result["results"][0]["doc_id"]

        result = _tool_call("get_document", {"doc_id": doc_id})
        assert result["doc_id"] == doc_id
        assert "title" in result
        assert "metadata" in result

    def test_get_document_not_found(self):
        """get_document returns error for unknown doc_id."""
        data = _mcp_call(
            "tools/call",
            {
                "name": "get_document",
                "arguments": {"doc_id": "nonexistent-doc-id-xyz"},
            },
        )
        result = data.get("result", {})
        assert result.get("isError") is True

    def test_auth_rejects_bad_key(self):
        """MCP server rejects requests with invalid API key."""
        resp = requests.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "X-API-Key": "invalid-key-xyz",
            },
            timeout=10,
        )
        assert resp.status_code in (401, 403)

    def test_filters_description_lists_data_sources(self):
        """filters field description includes data source info from config."""
        data = _mcp_call("tools/list")
        for tool in data["result"]["tools"]:
            if tool["name"] == "search":
                props = tool["inputSchema"]["properties"]
                filters_desc = props["filters"]["description"]
                assert "uneg" in filters_desc
                assert "include_facets" in filters_desc
                return
        pytest.fail("search tool not found")

    def test_data_source_description_from_config(self):
        """data_source field description lists configured sources."""
        data = _mcp_call("tools/list")
        for tool in data["result"]["tools"]:
            if tool["name"] == "search":
                props = tool["inputSchema"]["properties"]
                ds_desc = props["data_source"]["description"]
                assert "uneg" in ds_desc
                assert "Default:" in ds_desc
                return
        pytest.fail("search tool not found")
