"""A2A Agent Card builder for Evidence Lab."""

from __future__ import annotations

import os
from typing import List


def _datasource_names() -> List[str]:
    """Return the list of configured datasource names from config.json."""
    try:
        # get_application_config returns the application sub-key; load raw config for
        # the top-level datasources list
        import json

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        return list(raw.get("datasources", {}).keys())
    except Exception:
        return []


def _build_description(datasource_names: List[str]) -> str:
    if not datasource_names:
        return (
            "AI research agent for evaluation and policy documents. "
            "Searches document collections and synthesises answers with source citations."
        )
    if len(datasource_names) == 1:
        collections = datasource_names[0]
    elif len(datasource_names) == 2:
        collections = f"{datasource_names[0]} and {datasource_names[1]}"
    else:
        collections = ", ".join(datasource_names[:-1]) + f", and {datasource_names[-1]}"
    return (
        f"AI research agent for {collections}. "
        "Searches document collections and synthesises answers with source citations."
    )


def _build_research_description(datasource_names: List[str]) -> str:
    if not datasource_names:
        return (
            "Answer research questions across configured document collections. "
            "Returns a synthesised answer with inline citations and links to source documents."
        )
    collections = (
        "; ".join(datasource_names)
        if datasource_names
        else "configured document collections"
    )
    return (
        f"Answer research questions across: {collections}. "
        "Returns a synthesised answer with inline citations and links to source documents."
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
    datasource_names = _datasource_names()

    return AgentCard(
        name="Evidence Lab Research Agent",
        description=_build_description(datasource_names),
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
                description=_build_research_description(datasource_names),
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
                description=(
                    "Semantic search over document chunks. "
                    "Returns ranked text passages with metadata. "
                    "Accepts optional JSON filters for organisation, year, "
                    "country, SDG, etc. "
                    "Use this skill to retrieve raw evidence passages "
                    "when you want to analyse the data yourself."
                ),
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
