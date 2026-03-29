"""A2A Agent Card builder for Evidence Lab."""

from __future__ import annotations

import os
from typing import List


def _load_datasources() -> List[tuple]:
    """Return [(name, key), ...] for each configured datasource."""
    try:
        import json

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        return [
            (name, ds.get("data_subdir", name))
            for name, ds in raw.get("datasources", {}).items()
        ]
    except Exception:
        return []


def _build_description(datasources: List[tuple]) -> str:
    if not datasources:
        return (
            "AI research agent for evaluation and policy documents. "
            "Searches document collections and synthesises answers with source citations."
        )
    names = [name for name, _ in datasources]
    if len(names) == 1:
        collections = names[0]
    elif len(names) == 2:
        collections = f"{names[0]} and {names[1]}"
    else:
        collections = ", ".join(names[:-1]) + f", and {names[-1]}"
    return (
        f"AI research agent for {collections}. "
        "Searches document collections and synthesises answers with source citations."
    )


def _build_skill_description(datasources: List[tuple], skill: str) -> str:
    if not datasources:
        ds_list = "configured document collections"
        data_source_hint = ""
    else:
        entries = [f'"{key}" ({name})' for name, key in datasources]
        ds_list = "; ".join(entries)
        keys = [key for _, key in datasources]
        data_source_hint = (
            f" Pass data_source in message metadata to select a collection: "
            f"{', '.join(repr(k) for k in keys)}."
        )

    if skill == "research":
        return (
            f"Answer research questions across: {ds_list}."
            f"{data_source_hint}"
            " Returns a synthesised answer with inline citations and links to source documents."
        )
    return (
        f"Semantic search over: {ds_list}."
        f"{data_source_hint}"
        " Returns ranked text passages with metadata, scores, and citation links."
        " Use when you want to analyse the raw evidence yourself."
    )


def build_agent_card():  # type: ignore[return]
    """Build the Agent Card describing this A2A agent."""
    from a2a_server.schemas import (
        AgentAuthentication,
        AgentCapabilities,
        AgentCard,
        AgentSkill,
    )

    base_url = os.environ.get("APP_BASE_URL", "https://evidencelab.ai")
    a2a_url = f"{base_url}/a2a"
    datasources = _load_datasources()

    return AgentCard(
        name="Evidence Lab Research Agent",
        description=_build_description(datasources),
        url=a2a_url,
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=False,
        ),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        authentication=AgentAuthentication(
            schemes=["Bearer", "ApiKey"],
        ),
        documentationUrl=f"{base_url}/docs",
        skills=[
            AgentSkill(
                id="research",
                name="Research Evaluations",
                description=_build_skill_description(datasources, "research"),
                tags=["research", "evaluations", "evidence"],
                examples=[
                    "What are the main findings on climate adaptation in Africa?",
                    "How effective have school feeding programs been?",
                    "Compare approaches to gender mainstreaming across UN agencies",
                    "What does the evidence say about cash transfer programs?",
                ],
                inputModes=["text/plain"],
                outputModes=["text/plain"],
            ),
            AgentSkill(
                id="search",
                name="Search Evaluation Documents",
                description=_build_skill_description(datasources, "search"),
                tags=["search", "evaluations", "semantic"],
                examples=[
                    "Search for findings on food security in Yemen",
                    'Search for WASH recommendations {"organization": "UNICEF"}',
                ],
                inputModes=["text/plain"],
                outputModes=["application/json"],
            ),
        ],
    )
