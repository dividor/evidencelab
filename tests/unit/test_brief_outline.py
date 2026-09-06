"""Unit tests for Brief-tab outline generation (ui.backend.services.llm_service)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.backend.services.llm_service import generate_brief_outline, parse_brief_outline

pytestmark = pytest.mark.unit


class TestParseBriefOutline:
    def test_parse_outline_when_clean_json_then_title_and_levels(self):
        raw = (
            '{"title": "Cash Assistance", "headings": ['
            '{"title": "Background", "level": 1}, '
            '{"title": "Food security", "level": 2}, '
            '{"title": "Recommendations", "level": 1}]}'
        )
        title, headings = parse_brief_outline(raw)
        assert title == "Cash Assistance"
        assert [h["title"] for h in headings] == [
            "Background",
            "Food security",
            "Recommendations",
        ]
        assert [h["level"] for h in headings] == [1, 2, 1]

    def test_parse_outline_when_code_fenced_then_strips_fences(self):
        raw = '```json\n{"title": "T", "headings": [{"title": "A", "level": 1}]}\n```'
        title, headings = parse_brief_outline(raw)
        assert title == "T"
        assert headings == [{"title": "A", "level": 1}]

    def test_parse_outline_when_prose_around_json_then_extracts_object(self):
        raw = 'Sure! Here is the outline:\n{"title": "X", "headings": []}\nHope that helps.'
        title, headings = parse_brief_outline(raw, fallback_title="fallback")
        assert title == "X"
        # empty headings -> a single Overview section is supplied
        assert headings == [{"title": "Overview", "level": 1}]

    def test_parse_outline_when_first_heading_is_level2_then_forced_to_level1(self):
        raw = '{"title": "T", "headings": [{"title": "Sub", "level": 2}]}'
        _, headings = parse_brief_outline(raw)
        assert headings[0]["level"] == 1

    def test_parse_outline_when_not_json_then_falls_back_to_list(self):
        raw = "1. Background\n2. Effectiveness\n- Recommendations"
        title, headings = parse_brief_outline(raw, fallback_title="My question")
        assert title == "My question"
        assert [h["title"] for h in headings] == [
            "Background",
            "Effectiveness",
            "Recommendations",
        ]
        assert all(h["level"] == 1 for h in headings)

    def test_parse_outline_when_empty_then_overview_fallback(self):
        title, headings = parse_brief_outline("")
        assert title == "Evidence Brief"
        assert headings == [{"title": "Overview", "level": 1}]

    def test_parse_outline_caps_heading_count(self):
        items = ",".join(f'{{"title": "H{i}", "level": 1}}' for i in range(40))
        raw = '{"title": "T", "headings": [' + items + "]}"
        _, headings = parse_brief_outline(raw)
        assert len(headings) == 24


class TestGenerateBriefOutline:
    @pytest.mark.asyncio
    async def test_generate_outline_invokes_llm_and_parses(self):
        fake_response = MagicMock()
        fake_response.content = (
            '{"title": "Anticipatory Action", "headings": ['
            '{"title": "Overview", "level": 1}, '
            '{"title": "Flood programmes", "level": 2}]}'
        )
        fake_llm = MagicMock()
        fake_llm.ainvoke = AsyncMock(return_value=fake_response)

        with patch(
            "ui.backend.services.llm_service.get_llm", return_value=fake_llm
        ) as mock_get_llm:
            title, headings, usage = await generate_brief_outline(
                question="How effective is anticipatory action for floods?",
                model_key="some-model",
            )

        mock_get_llm.assert_called_once()
        assert mock_get_llm.call_args.kwargs["model"] == "some-model"
        # The question is sent to the LLM in the user message.
        sent_messages = fake_llm.ainvoke.call_args.args[0]
        assert any(
            "anticipatory action" in str(m.content).lower() for m in sent_messages
        )
        assert title == "Anticipatory Action"
        assert [h["title"] for h in headings] == ["Overview", "Flood programmes"]
        assert [h["level"] for h in headings] == [1, 2]
        # Usage payload carries the model key (mock reports no token counts).
        assert usage == {"llm_model": "some-model"}
