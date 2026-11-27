"""Verify MCP Apps metadata, tool responses, authorization, and accounting."""

import secrets
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcp_server import http_server, oauth, rate_limit
from mcp_server.app import mcp
from mcp_server.audit import request_auth
from mcp_server.data_source_access import MCPSourceDenied, resolve_mcp_source
from mcp_server.resources.heatmap import (
    HEATMAP_MIME_TYPE,
    HEATMAP_URI,
    read_heatmap_html,
    resource_metadata,
)
from mcp_server.tools import heatmap as adapter
from ui.backend.schemas import Facets, FacetValue
from ui.backend.schemas.heatmap import HeatmapRequest
from ui.backend.services import heatmap, heatmap_axes
from ui.backend.services.heatmap_search import CellHits, HeatmapHit

pytestmark = pytest.mark.unit


@pytest.fixture
def grid_request():
    return HeatmapRequest(
        data_source="uneg",
        row_dimension="queries",
        column_dimension="published_year",
        row_queries=["School | meals & nutrition", "Quality <data>"],
        filters={"organization": "UNICEF"},
        column_values=["2024"],
    )


@pytest.fixture
def planned_grid(grid_request):
    facets = Facets(
        filter_fields={"published_year": "Year Published"},
        facets={"published_year": [FacetValue(value="2024", count=10)]},
    )
    return heatmap_axes.plan_axes(grid_request, facets, 24)


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(
        rate_limit, "_limiter", MovingWindowRateLimiter(MemoryStorage())
    )
    monkeypatch.setitem(rate_limit._LIMITS, "search", "30/minute")


@pytest.mark.asyncio
async def test_stateless_wire_grid_and_app_only_drill_down(
    planned_grid, monkeypatch, tmp_path, budget
):
    credential = secrets.token_urlsafe(32)
    monkeypatch.setenv("API_SECRET_KEY", credential)
    monkeypatch.setenv("MCP_APP_ASSET_DIR", str(tmp_path))
    monkeypatch.setattr(http_server, "REQUIRE_AUTH", True)
    monkeypatch.setattr(oauth, "_APP_BASE_URL", "https://example.org/evidence/")
    (tmp_path / "heatmap.html").write_text(
        "<!doctype html><title>App</title>", encoding="utf-8"
    )
    plan = Mock(return_value=planned_grid)
    monkeypatch.setattr(heatmap_axes, "plan_heatmap", plan)
    monkeypatch.setattr(
        heatmap,
        "search_cell",
        AsyncMock(
            return_value=CellHits(
                [
                    HeatmapHit("1", "doc", 1.0, "One"),
                    HeatmapHit("2", "other", 0.1, "Other"),
                ],
                False,
            )
        ),
    )
    audit = Mock()
    monkeypatch.setattr(adapter, "log_mcp_call", audit)
    headers = {"X-API-Key": credential, "Accept": "application/json, text/event-stream"}

    manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=True,
        stateless=True,
    )
    monkeypatch.setattr(http_server, "session_manager", manager)
    async with manager.run(), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_server.app),
        base_url="http://test",
    ) as client:

        async def rpc(method, params, authenticated=True):
            incoming = headers if authenticated else {"Accept": headers["Accept"]}
            return await client.post(
                "/mcp",
                headers=incoming,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )

        listed = await rpc("tools/list", {})
        tools = {item["name"]: item for item in listed.json()["result"]["tools"]}
        assert tools["heatmap"]["_meta"]["ui"]["resourceUri"] == HEATMAP_URI
        assert tools["heatmap"]["_meta"]["ui/resourceUri"] == HEATMAP_URI
        assert tools["heatmap_cell"]["_meta"]["ui"]["visibility"] == ["app"]
        assert "24 cells" in tools["heatmap"]["description"]

        resource = await rpc("resources/read", {"uri": HEATMAP_URI})
        entry = resource.json()["result"]["contents"][0]
        assert entry["mimeType"] == HEATMAP_MIME_TYPE
        assert entry["text"] == "<!doctype html><title>App</title>"
        assert entry["_meta"] == resource_metadata(oauth.public_mcp_url())

        response = await rpc(
            "tools/call",
            {
                "name": "heatmap",
                "arguments": {"request": planned_grid.request.model_dump()},
            },
        )
        assert "mcp-session-id" not in response.headers
        result = response.json()["result"]
        assert not result["isError"], result
        grid = result["structuredContent"]
        assert grid["counts"] == [[1], [1]]
        assert "School \\| meals" in result["content"][0]["text"]
        assert "Quality &lt;data&gt;" in result["content"][0]["text"]
        link = urlsplit(grid["web_url"])
        assert link.path == "/evidence/"
        params = parse_qs(link.query)
        assert params["hm_row_q"] == planned_grid.request.row_queries
        assert params["dataset"] == ["UN Humanitarian Evaluation Reports"]
        assert params["published_year"] == ["2024"]
        assert params["hm_sens"] == [str(grid["cutoff"])]
        cell_args = {
            "name": "heatmap_cell",
            "arguments": {
                "request": {
                    "grid": grid["request"],
                    "row": 1,
                    "column": 0,
                    "cutoff": grid["cutoff"],
                    "fingerprint": grid["fingerprints"][1][0],
                }
            },
        }
        denied = await rpc("tools/call", cell_args, authenticated=False)
        assert denied.status_code == 401
        cell = await rpc("tools/call", cell_args)
        assert "mcp-session-id" not in cell.headers
        assert (
            cell.json()["result"]["structuredContent"]["documents"][0]["doc_id"]
            == "doc"
        )

    assert [call.kwargs["status"] for call in audit.call_args_list] == ["ok", "ok"]
    assert all(
        call.kwargs["auth_info"]["type"] == "api_key" for call in audit.call_args_list
    )


def test_resource_domain_hashes_the_exact_public_connector_url():
    assert resource_metadata("https://example.com/mcp") == {
        "ui": {
            "csp": {},
            "domain": "c3d80a4ed901ee05b21755a88273b4a4.claudemcpcontent.com",
        }
    }
    assert resource_metadata("https://example.com/mcp/") != resource_metadata(
        "https://example.com/mcp"
    )


@pytest.mark.asyncio
async def test_missing_resource_has_no_filesystem_details(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_APP_ASSET_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="asset is unavailable") as result:
        await read_heatmap_html()
    assert str(tmp_path) not in str(result.value)


@pytest.mark.asyncio
async def test_grid_reserves_budget_before_any_cell_work(
    planned_grid, monkeypatch, budget
):
    monkeypatch.setitem(rate_limit._LIMITS, "search", "3/minute")
    rate_limit.check_caller_rate_limit("search")
    monkeypatch.setattr(heatmap_axes, "plan_heatmap", Mock(return_value=planned_grid))
    run = AsyncMock()
    monkeypatch.setattr(heatmap, "build_heatmap", run)
    audit = Mock()
    monkeypatch.setattr(adapter, "log_mcp_call", audit)

    error = await adapter.heatmap(planned_grid.request)

    assert error.isError
    assert "Rate limit exceeded" in error.content[0].text
    run.assert_not_awaited()
    assert audit.call_args.kwargs["status"] == "error"
    rate_limit.check_caller_rate_limit("search")
    with pytest.raises(rate_limit.McpRateLimitExceeded):
        rate_limit.check_caller_rate_limit("search")


@pytest.mark.asyncio
async def test_denied_jwt_source_does_not_read_facets(
    planned_grid, monkeypatch, budget
):
    monkeypatch.setattr(
        adapter,
        "resolve_mcp_source",
        AsyncMock(side_effect=MCPSourceDenied("Access denied.")),
    )
    plan = Mock()
    monkeypatch.setattr(heatmap_axes, "plan_heatmap", plan)
    monkeypatch.setattr(adapter, "log_mcp_call", Mock())

    error = await adapter.heatmap(planned_grid.request)

    assert error.isError
    assert error.content[0].text == "Access denied."
    plan.assert_not_called()


@pytest.mark.asyncio
async def test_backend_error_is_sanitized(planned_grid, monkeypatch, budget):
    monkeypatch.setattr(
        heatmap_axes,
        "plan_heatmap",
        Mock(side_effect=PermissionError("/private/server/path")),
    )
    monkeypatch.setattr(adapter, "log_mcp_call", Mock())

    error = await adapter.heatmap(planned_grid.request)

    assert error.isError
    assert "/private/server/path" not in error.content[0].text


@pytest.mark.asyncio
async def test_jwt_uses_group_access_and_api_key_uses_configured_sources(monkeypatch):
    check_access = AsyncMock()
    monkeypatch.setattr(
        "mcp_server.data_source_access.check_group_access", check_access
    )
    token = request_auth.set({"type": "jwt", "user_id": "sample-user"})
    try:
        assert await resolve_mcp_source("uneg") == "uneg"
        check_access.assert_awaited_once_with("uneg", "sample-user")
    finally:
        request_auth.reset(token)
    token = request_auth.set({"type": "api_key", "key_hash": "test"})
    try:
        assert await resolve_mcp_source("uneg") == "uneg"
        with pytest.raises(ValueError, match="Invalid data source"):
            await resolve_mcp_source("unconfigured-source")
    finally:
        request_auth.reset(token)
    assert check_access.await_count == 1


@pytest.mark.asyncio
async def test_original_tools_remain_registered():
    assert {"search", "get_document"} <= {tool.name for tool in await mcp.list_tools()}


@pytest.mark.asyncio
async def test_signed_in_group_guard_uses_current_user_record(monkeypatch):
    from uuid import uuid4

    from fastapi import HTTPException

    from mcp_server.data_source_access import check_group_access

    user_id = uuid4()
    user = Mock(is_active=True)
    db = AsyncMock()
    db.get.return_value = user
    factory = Mock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    check = AsyncMock()
    monkeypatch.setattr("ui.backend.auth.optional_user.USER_MODULE_ENABLED", True)
    monkeypatch.setattr("ui.backend.auth.db.async_session_factory", factory)
    monkeypatch.setattr(
        "ui.backend.services.permissions.ensure_data_source_access", check
    )

    await check_group_access("uneg", str(user_id))
    assert db.get.await_args.args[1] == user_id
    check.assert_awaited_once_with(db, user, "uneg")

    check.side_effect = HTTPException(status_code=403, detail="Internal group decision")
    with pytest.raises(MCPSourceDenied, match="don't have access"):
        await check_group_access("uneg", str(user_id))

    user.is_active = False
    with pytest.raises(MCPSourceDenied, match="Sign in"):
        await check_group_access("uneg", str(user_id))
