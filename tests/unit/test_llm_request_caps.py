"""Requests cannot ask for more than config.json and the size settings allow.

The AI routes take a model and an output-token budget from the request, and
the search and highlight routes take sizes. With the browser's key public,
these are the only things that bound what one request can cost.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pipeline.db import config as db_config
from ui.backend.utils.app_limits import limiter
from ui.backend.utils.llm_request_limits import check_requested_llm, max_output_tokens

SUPPORTED = {
    "small-model": {"model": "vendor/small-model-v1", "provider": "huggingface"},
    "big-model": {
        "model": "big-model",
        "provider": "google_vertex",
        "max_tokens": 65536,
    },
}
COMBOS = {
    "A": {
        "summarization_model": {"model": "small-model", "max_tokens": 2000},
        "semantic_highlighting_model": {"model": "small-model", "max_tokens": 500},
        "assistant_model": {"model": "small-model", "max_tokens": 2000},
    },
    "B": {"summarization_model": {"model": "big-model", "max_tokens": 1500}},
}


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(db_config, "SUPPORTED_LLMS", SUPPORTED)
    monkeypatch.setattr(db_config, "UI_MODEL_COMBOS", COMBOS)


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


def test_max_output_tokens_when_model_in_combos_then_largest_combo_value():
    assert max_output_tokens("small-model") == 2000
    assert max_output_tokens("vendor/small-model-v1") == 2000


def test_max_output_tokens_when_model_has_own_max_then_it_counts():
    assert max_output_tokens("big-model") == 65536


def test_max_output_tokens_when_no_model_then_largest_any_combo_sets():
    assert max_output_tokens(None) == 2000


@pytest.mark.parametrize("model", ["small-model", "vendor/small-model-v1", None])
def test_check_when_configured_model_within_budget_then_allowed(model):
    check_requested_llm(model, 2000)


@pytest.mark.parametrize("model", ["gpt-unlisted", "anthropic/expensive"])
def test_check_when_model_not_configured_then_400(model):
    with pytest.raises(HTTPException) as exc:
        check_requested_llm(model, 100)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("tokens", [0, -5, 2001, 100_000])
def test_check_when_max_tokens_out_of_range_then_400(tokens):
    with pytest.raises(HTTPException) as exc:
        check_requested_llm("small-model", tokens)
    assert exc.value.status_code == 400
    assert "2000" in exc.value.detail


# ---------------------------------------------------------------------------
# Routes refuse before doing any work
# ---------------------------------------------------------------------------


def _app(router) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    return TestClient(app)


def _model_config(model: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "chunk_overlap": 0,
        "chunk_tokens_ratio": 0.5,
    }


@pytest.mark.parametrize("path", ["/ai-summary", "/ai-summary/stream"])
@pytest.mark.parametrize(
    "model,tokens", [("gpt-unlisted", 100), ("small-model", 100_000)]
)
def test_ai_summary_when_model_or_budget_not_allowed_then_400(path, model, tokens):
    from ui.backend.routes import summary

    body = {
        "query": "q",
        "results": [],
        "summary_model_config": _model_config(model, tokens),
    }
    response = _app(summary.router).post(path, json=body)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "model,tokens", [("gpt-unlisted", 100), ("small-model", 100_000)]
)
def test_highlight_when_model_or_budget_not_allowed_then_400(model, tokens):
    from ui.backend.routes import highlight

    body = {
        "query": "q",
        "text": "some text",
        "highlight_type": "semantic",
        "semantic_model_config": _model_config(model, tokens),
    }
    assert _app(highlight.router).post("/highlight", json=body).status_code == 400


def test_highlight_when_text_too_long_then_400(monkeypatch):
    from ui.backend.routes import highlight

    monkeypatch.setattr(highlight, "HIGHLIGHT_MAX_TEXT_CHARS", 1000)
    body = {"query": "q", "text": "x" * 1001, "highlight_type": "keyword"}
    response = _app(highlight.router).post("/highlight", json=body)
    assert response.status_code == 400


def test_search_when_limit_above_maximum_then_422():
    from ui.backend.routes import search

    client = _app(search.router)
    too_many = search.SEARCH_MAX_LIMIT + 1
    assert client.get(f"/search?q=x&limit={too_many}").status_code == 422
    assert client.get("/search?q=x&limit=0").status_code == 422
    facet = f"/search/facet-values?field=organization&q=x&limit={too_many}"
    assert client.get(facet).status_code == 422


# ---------------------------------------------------------------------------
# MCP and A2A: counted per caller
# ---------------------------------------------------------------------------


def test_mcp_rate_limit_when_caller_exceeds_then_refused_and_others_unaffected(
    monkeypatch,
):
    from mcp_server import rate_limit
    from mcp_server.audit import request_auth

    monkeypatch.setitem(rate_limit._LIMITS, "ai", "2/minute")
    monkeypatch.setattr(
        rate_limit,
        "_limiter",
        rate_limit.MovingWindowRateLimiter(rate_limit.MemoryStorage()),
    )

    token = request_auth.set(
        {"type": "api_key", "user_id": "u", "key_hash": "caller-a"}
    )
    try:
        rate_limit.check_caller_rate_limit("ai")
        rate_limit.check_caller_rate_limit("ai")
        with pytest.raises(rate_limit.McpRateLimitExceeded):
            rate_limit.check_caller_rate_limit("ai")
    finally:
        request_auth.reset(token)

    token = request_auth.set({"type": "jwt", "user_id": "caller-b", "key_hash": None})
    try:
        rate_limit.check_caller_rate_limit("ai")
    finally:
        request_auth.reset(token)


@pytest.mark.asyncio
async def test_mcp_search_when_over_limit_then_refused_before_searching(monkeypatch):
    from mcp_server import rate_limit
    from mcp_server.audit import request_auth
    from mcp_server.tools.search import mcp_search

    monkeypatch.setitem(rate_limit._LIMITS, "search", "1/minute")
    monkeypatch.setattr(
        rate_limit,
        "_limiter",
        rate_limit.MovingWindowRateLimiter(rate_limit.MemoryStorage()),
    )
    token = request_auth.set(
        {"type": "api_key", "user_id": "u", "key_hash": "caller-c"}
    )
    try:
        rate_limit.check_caller_rate_limit("search")
        with pytest.raises(rate_limit.McpRateLimitExceeded):
            await mcp_search(query="anything")
    finally:
        request_auth.reset(token)
