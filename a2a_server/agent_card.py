"""A2A Agent Card builder for Evidence Lab."""

from __future__ import annotations

import os

from a2a_server.schemas import (
    AgentAuthentication,
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)


def build_agent_card() -> AgentCard:
    """Build the Agent Card describing this A2A agent."""
    base_url = os.environ.get("APP_BASE_URL", "https://evidencelab.ai")
    a2a_url = f"{base_url}/a2a"

    return AgentCard(
        name="Evidence Lab Research Agent",
        description=(
            "AI research agent for evaluation documents from UN agencies, "
            "World Bank, and other development organisations. "
            "Searches ~15,000 evaluation reports and synthesises answers "
            "with source citations."
        ),
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
                description=(
                    "Answer research questions about humanitarian and development "
                    "evaluation documents. Searches across UN agency evaluations "
                    "(UNDP, UNICEF, WFP, FAO, ILO and 20+ others), World Bank "
                    "integrity reports, and UN Mandates Registry resolutions. "
                    "Returns a synthesised answer with inline citations and "
                    "links to source documents."
                ),
                tags=["research", "evaluations", "UN", "humanitarian", "development"],
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
                    "Semantic search over evaluation document chunks. "
                    "Returns ranked text passages with metadata. "
                    "Accepts optional JSON filters for organisation, year, "
                    "country, SDG, etc. "
                    "Use this skill to retrieve raw evidence passages "
                    "when you want to analyse the data yourself."
                ),
                tags=["search", "evaluations", "semantic"],
                examples=[
                    "Search for findings on food security in Yemen",
                    "Search uneg for WASH recommendations"
                    ' {"organization": "UNICEF"}',
                ],
                inputModes=["text/plain"],
                outputModes=["application/json"],
            ),
        ],
    )
