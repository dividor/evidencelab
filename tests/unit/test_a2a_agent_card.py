"""Unit tests for the A2A Agent Card."""

from __future__ import annotations

from a2a_server.agent_card import build_agent_card


class TestBuildAgentCard:
    def test_returns_agent_card(self):
        card = build_agent_card()
        assert card.name == "Evidence Lab Research Agent"
        assert card.version == "1.0.0"

    def test_url_uses_app_base_url(self, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://example.com")
        card = build_agent_card()
        assert card.url == "https://example.com/a2a"

    def test_url_defaults_to_evidencelab(self, monkeypatch):
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        card = build_agent_card()
        assert card.url == "https://evidencelab.ai/a2a"

    def test_has_research_skill(self):
        card = build_agent_card()
        ids = [s.id for s in card.skills]
        assert "research" in ids

    def test_has_search_skill(self):
        card = build_agent_card()
        ids = [s.id for s in card.skills]
        assert "search" in ids

    def test_streaming_enabled(self):
        card = build_agent_card()
        assert card.capabilities.streaming is True

    def test_auth_schemes(self):
        card = build_agent_card()
        assert "Bearer" in card.authentication.schemes
        assert "ApiKey" in card.authentication.schemes

    def test_serialises_to_json(self):
        import json

        card = build_agent_card()
        data = json.loads(card.model_dump_json(exclude_none=True))
        assert data["name"] == "Evidence Lab Research Agent"
        assert "skills" in data
        assert len(data["skills"]) == 2
