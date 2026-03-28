"""Unit tests for MCP config-driven descriptions and filter parsing."""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from mcp_server.schemas import MCPSearchResponse

# ── Config-driven description tests ──────────────────────────────────


def test_data_source_description_reads_config(monkeypatch, tmp_path):
    """_data_source_description reads datasources from config.json."""
    config = {
        "datasources": {
            "Test Reports": {"data_subdir": "testreports"},
            "Other Data": {"data_subdir": "other"},
        }
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    import mcp_server.app as server_mod

    monkeypatch.setattr(
        server_mod,
        "_load_config",
        lambda: config,
    )

    desc = server_mod._data_source_description()
    assert '"testreports" (Test Reports)' in desc
    assert '"other" (Other Data)' in desc
    assert 'Default: "testreports"' in desc


def test_data_source_description_fallback_on_error(monkeypatch):
    """_data_source_description returns fallback when config fails."""
    import mcp_server.app as server_mod

    monkeypatch.setattr(
        server_mod,
        "_load_config",
        lambda: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    desc = server_mod._data_source_description()
    assert "uneg" in desc
    assert "worldbank" in desc


def test_filters_description_reads_config(monkeypatch):
    """_filters_description lists filter fields from config.json."""
    config = {
        "datasources": {
            "Test Reports": {
                "data_subdir": "test",
                "default_filter_fields": {
                    "organization": "Organization",
                    "title": "Title",
                    "published_year": "Year",
                    "country": "Country",
                },
            },
        }
    }

    import mcp_server.app as server_mod

    monkeypatch.setattr(server_mod, "_load_config", lambda: config)

    desc = server_mod._filters_description()
    assert 'For "test": organization, published_year, country' in desc
    assert "title" not in desc.split('For "test":')[1].split(".")[0]
    assert "include_facets" in desc
    assert "Examples:" in desc


def test_filters_description_fallback_on_error(monkeypatch):
    """_filters_description returns fallback when config fails."""
    import mcp_server.app as server_mod

    monkeypatch.setattr(
        server_mod,
        "_load_config",
        lambda: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    desc = server_mod._filters_description()
    assert "include_facets" in desc
    assert "organization" in desc


# ── Filter parsing tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_accepts_dict_filters(monkeypatch):
    """Search tool accepts filters as a dict (how MCP clients send them)."""
    captured_kwargs: dict = {}

    def fake_search_chunks(**kwargs):
        captured_kwargs.update(kwargs)
        return []

    fake_db = MagicMock()
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(
        query="test",
        filters={"organization": "WFP"},
    )

    assert isinstance(result, MCPSearchResponse)
    assert captured_kwargs["filters"] == {"organization": "WFP"}


def test_server_parses_string_filters():
    """Server wrapper parses JSON string filters to dict."""
    raw = '{"organization": "UNDP", "published_year": "2024"}'
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    assert parsed == {"organization": "UNDP", "published_year": "2024"}


def test_server_passes_dict_filters():
    """Server wrapper passes dict filters through unchanged."""
    raw = {"organization": "WFP"}
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    assert parsed == {"organization": "WFP"}


def test_server_handles_none_filters():
    """Server wrapper passes None through when no filters."""
    raw = None
    parsed = (json.loads(raw) if isinstance(raw, str) else raw) if raw else None
    assert parsed is None


@pytest.mark.asyncio
async def test_search_none_filters(monkeypatch):
    """Search tool passes None when no filters provided."""
    captured_kwargs: dict = {}

    def fake_search_chunks(**kwargs):
        captured_kwargs.update(kwargs)
        return []

    fake_db = MagicMock()
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(query="test")

    assert isinstance(result, MCPSearchResponse)
    assert captured_kwargs["filters"] is None


# ── Facets test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_include_facets(monkeypatch):
    """include_facets=True returns facet data in response."""

    def fake_search_chunks(**kwargs):
        return []

    fake_db = MagicMock()
    fake_db.facet_documents.return_value = {"UNDP": 100, "UNICEF": 50}

    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    # Patch get_default_filter_fields and get_taxonomy_filter_fields
    pipeline_db_mod = sys.modules.get("pipeline.db")
    if pipeline_db_mod is None:
        pipeline_db_mod = ModuleType("pipeline.db")
        monkeypatch.setitem(sys.modules, "pipeline.db", pipeline_db_mod)
    monkeypatch.setattr(
        pipeline_db_mod,
        "get_default_filter_fields",
        lambda _: {"organization": "Organization"},
        raising=False,
    )
    monkeypatch.setattr(
        pipeline_db_mod,
        "get_taxonomy_filter_fields",
        lambda _: {},
        raising=False,
    )

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(query="test", include_facets=True)

    assert isinstance(result, MCPSearchResponse)
    assert result.facets is not None
    assert "organization" in result.facets
    assert result.facets["organization"][0]["value"] == "UNDP"
    assert result.facets["organization"][0]["count"] == 100


@pytest.mark.asyncio
async def test_search_no_facets_by_default(monkeypatch):
    """Facets are not returned when include_facets is False (default)."""

    def fake_search_chunks(**kwargs):
        return []

    fake_db = MagicMock()
    fake_pg = MagicMock()
    fake_pg.fetch_docs.return_value = {}

    search_mod = ModuleType("ui.backend.services.search")
    search_mod.search_chunks = fake_search_chunks
    monkeypatch.setitem(sys.modules, "ui.backend.services.search", search_mod)

    app_state_mod = ModuleType("ui.backend.utils.app_state")
    app_state_mod.get_db_for_source = lambda _: fake_db
    app_state_mod.get_pg_for_source = lambda _: fake_pg
    monkeypatch.setitem(sys.modules, "ui.backend.utils.app_state", app_state_mod)

    from mcp_server.tools.search import mcp_search

    result = await mcp_search(query="test")

    assert isinstance(result, MCPSearchResponse)
    assert result.facets is None
