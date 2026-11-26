"""Validation and runtime rules for group Assistant settings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request

from ui.backend.auth.schemas import AssistantChatRequest
from ui.backend.routes import assistant as assistant_routes
from ui.backend.services.assistant_graph import build_research_agent
from ui.backend.services.assistant_settings import (
    AssistantSettings,
    assistant_settings_for_groups,
    assistant_site_defaults,
    validate_assistant_settings,
)
from ui.backend.services.group_settings import merge_group_settings

pytestmark = pytest.mark.unit


@pytest.fixture
def models(monkeypatch):
    from pipeline.db import config

    monkeypatch.setattr(
        config,
        "SUPPORTED_LLMS",
        {
            "first": {"model": "provider-first", "max_tokens": 2000},
            "second": {"model": "provider-second", "max_tokens": 4000},
        },
    )


def test_admin_can_save_a_complete_assistant_override(models):
    payload = {
        "assistant": {
            "model": "first",
            "temperature": 0,
            "maxTokens": 1000,
            "planningPrompt": "  Compare independently. ",
            "answerPrompt": "Show the limits.",
            "searches": 4,
            "searchesPerStream": 2,
            "deepSearches": 12,
            "deepSearchesPerStream": 3,
            "deepResearchByDefault": False,
        },
        "rerank": False,
    }
    validate_assistant_settings(payload)
    assert payload["assistant"]["planningPrompt"] == "Compare independently."
    assert payload["assistant"]["deepResearchByDefault"] is False
    assert payload["rerank"] is False


def test_site_defaults_show_the_configured_search_budgets_and_builtin_prompts(
    monkeypatch,
):
    from pipeline.db import config

    monkeypatch.setattr(
        config,
        "get_application_config",
        lambda: {"assistant": {"max_queries": 3, "deep_research": {"max_queries": 8}}},
    )
    defaults = assistant_site_defaults()
    assert defaults.search_limits(False) == (3, 2)
    assert defaults.search_limits(True) == (8, 4)
    assert defaults.deepResearchByDefault is False
    assert "concrete gap" in (defaults.planningInstructions or "")
    assert "Synthesize across relevant passages" in (defaults.answerInstructions or "")


@pytest.mark.parametrize(
    "settings",
    [
        {"temperature": 1.5},
        {"searches": "4"},
        {"deepSearchesPerStream": 7},
        {"model": "unavailable"},
        {"model": "first", "maxTokens": 2001},
        {"planningPrompt": "x" * 12001},
        {"unknown": "key"},
    ],
)
def test_invalid_assistant_settings_are_rejected_at_save(models, settings):
    with pytest.raises(HTTPException) as error:
        validate_assistant_settings({"assistant": settings})
    assert error.value.status_code == 422


def test_group_order_merges_each_override_and_only_exposes_starting_mode():
    groups = [
        SimpleNamespace(
            search_settings={
                "assistant": {
                    "deepResearchByDefault": False,
                    "planningPrompt": "The first planning prompt",
                }
            }
        ),
        SimpleNamespace(
            search_settings={
                "assistant": {
                    "deepResearchByDefault": True,
                    "planningPrompt": "A second planning prompt",
                    "answerPrompt": "Report differences.",
                }
            }
        ),
    ]
    settings = assistant_settings_for_groups(groups)
    assert settings.planningPrompt == "The first planning prompt"
    assert settings.answerPrompt == "Report differences."
    assert merge_group_settings(groups) == {"assistantDeepResearchByDefault": False}


def test_effective_model_and_output_budget_respect_the_current_model(models):
    assert AssistantSettings(model="first", temperature=0.25).model_options(
        "second", 0, 4000
    ) == (
        "first",
        0.25,
        2000,
    )
    assert AssistantSettings(maxTokens=3500).model_options("first", 0, 1000) == (
        "first",
        0,
        2000,
    )
    with pytest.raises(HTTPException) as error:
        AssistantSettings(model="retired").model_options("first", 0, 1500)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("deep", "searches", "per_stream"), [(False, 3, 1), (True, 11, 5)]
)
def test_workflow_uses_group_prompts_and_limits_for_both_modes(
    deep, searches, per_stream
):
    settings = AssistantSettings(
        planningPrompt="Check inclusion by age.",
        answerPrompt="State uncertainty.",
        searches=3,
        searchesPerStream=1,
        deepSearches=11,
        deepSearchesPerStream=5,
    )
    with patch("ui.backend.services.assistant_graph.build_research_workflow") as build:
        _, _, budget = build_research_agent(
            MagicMock(),
            "wfp",
            system_prompt_override="Old summary prompt",
            assistant_settings=settings,
            deep_research=deep,
        )
    _, _, planner, writer, limits, opening = build.call_args.args
    assert limits.searches == budget == searches
    assert limits.searches_per_stream == per_stream
    assert "Check inclusion by age." in planner and "Check inclusion by age." in opening
    assert "State uncertainty." in writer and "Old summary prompt" not in writer


@pytest.mark.asyncio
async def test_assistant_settings_are_loaded_for_assistant_chat_and_kept_out_of_briefs():
    user = SimpleNamespace(id="test-user")
    session = MagicMock()
    groups = [SimpleNamespace(search_settings={"assistant": {"searches": 2}})]
    with (
        patch.object(assistant_routes, "_USER_MODULE", True),
        patch.object(
            assistant_routes, "user_groups", AsyncMock(return_value=groups)
        ) as load,
    ):
        brief = await assistant_routes._assistant_settings(
            AssistantChatRequest(query="Brief question", usage_context="brief"),
            user,
            session,
        )
        assert brief == AssistantSettings()
        load.assert_not_awaited()
        chat = await assistant_routes._assistant_settings(
            AssistantChatRequest(query="Assistant question"), user, session
        )
    assert chat.searches == 2
    load.assert_awaited_once_with(session, user.id)


@pytest.mark.asyncio
async def test_assistant_chat_passes_saved_group_options_to_research(models):
    overrides = {
        "model": "first",
        "temperature": 0.25,
        "maxTokens": 1500,
        "answerPrompt": "Discuss the quality of the evidence.",
        "deepSearchesPerStream": 3,
    }
    groups = [SimpleNamespace(search_settings={"assistant": overrides})]

    async def events():
        yield {"type": "phase", "phase": "planning"}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/assistant/chat/stream",
            "app": FastAPI(),
        }
    )
    with (
        patch.object(assistant_routes, "_USER_MODULE", True),
        patch.object(assistant_routes, "user_groups", AsyncMock(return_value=groups)),
        patch.object(
            assistant_routes, "settle_data_source", AsyncMock(return_value="wfp")
        ),
        patch.object(
            assistant_routes, "stream_research_response", return_value=events()
        ) as stream,
        patch.object(assistant_routes.limiter, "enabled", False),
    ):
        response = await assistant_routes.stream_assistant_chat(
            request,
            AssistantChatRequest(query="Compare the evidence", deep_research=True),
            user=SimpleNamespace(id="test-user"),
            session=MagicMock(),
        )
        chunks = [chunk async for chunk in response.body_iterator]

    assert '"phase": "planning"' in chunks[0]
    options = stream.call_args.kwargs
    assert (options["model_key"], options["temperature"], options["max_tokens"]) == (
        "first",
        0.25,
        1500,
    )
    assert options["assistant_settings"] == AssistantSettings(**overrides)
    assert options["system_prompt_override"] == overrides["answerPrompt"]
