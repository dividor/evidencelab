"""Unit tests for Brief introduction sections (``introduces_sub_sections``).

A top-level Brief heading with sub-headings is written as a short introduction:
no headings of its own and none of the detail its sub-sections cover. The
Brief sends the sub-headings; the deep-research answer prompt then replaces its
structure and heading rules with introduction rules, and the revise prompt
(AI Edit, condense) keeps the section an introduction. Requests without the
field, including every Research Assistant request, are unchanged.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment, FileSystemLoader
from pydantic import ValidationError

from ui.backend.auth.schemas import AssistantChatRequest
from ui.backend.schemas import BriefReviseRequest
from ui.backend.services.assistant_graph import (
    _load_deep_research_prompt,
    build_deep_research_agent,
)
from ui.backend.services.llm_service import _brief_revise_user_template

pytestmark = pytest.mark.unit

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
SUBS = ["Enrolment and attendance", "Learning and nutrition outcomes"]
INTRO_MARKER = "INTRODUCTION ONLY"
HEADING_RULE = "Use markdown: headings (##)"
DEFAULT_STRUCTURE_RULE = (
    "Structure your answer as several paragraphs with clear headings"
)
DEFAULT_LENGTH_RULE = "AT LEAST 3-4 paragraphs"


@pytest.fixture
def coordinator():
    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)
    return env.get_template("assistant_deep_research_coordinator.j2")


class TestCoordinatorIntroductionRules:
    def test_without_sub_sections_the_prompt_is_unchanged(self, coordinator):
        result = coordinator.render()
        assert INTRO_MARKER not in result
        assert HEADING_RULE in result
        assert DEFAULT_STRUCTURE_RULE in result
        assert DEFAULT_LENGTH_RULE in result

    def test_an_introduction_names_its_sub_sections_and_forbids_headings(
        self, coordinator
    ):
        result = coordinator.render(intro_sub_sections=SUBS)
        assert INTRO_MARKER in result
        for sub in SUBS:
            assert f"- {sub}" in result
        assert "NO headings of any level" in result

    def test_an_introduction_drops_every_rule_that_asks_for_headings(self, coordinator):
        result = coordinator.render(intro_sub_sections=SUBS)
        assert HEADING_RULE not in result
        assert DEFAULT_STRUCTURE_RULE not in result
        assert DEFAULT_LENGTH_RULE not in result
        assert "clear headings" not in result

    def test_an_introduction_with_a_long_target_still_has_no_headings(
        self, coordinator
    ):
        result = coordinator.render(intro_sub_sections=SUBS, target_words=700)
        # A length is a ceiling for an introduction, not a firm target to fill.
        assert "at most about 700 words" in result
        assert "FIRM TARGET" not in result
        assert "only as many headings as the length can carry" not in result
        assert "NO headings of any level" in result

    def test_the_loader_passes_the_sub_sections_through(self):
        assert INTRO_MARKER in _load_deep_research_prompt(introduces_sub_sections=SUBS)
        assert INTRO_MARKER not in _load_deep_research_prompt()


class TestBuildDeepResearchAgentIntroduction:
    @patch("ui.backend.services.assistant_graph.create_deep_agent")
    def test_sub_sections_reach_the_coordinator_system_prompt(self, mock_create):
        mock_create.return_value = MagicMock()
        build_deep_research_agent(
            MagicMock(), data_source="wfp", introduces_sub_sections=SUBS
        )
        system_prompt = mock_create.call_args.kwargs["system_prompt"]
        assert INTRO_MARKER in system_prompt
        assert HEADING_RULE not in system_prompt

    @patch("ui.backend.services.assistant_graph.create_deep_agent")
    def test_research_assistant_requests_are_unaffected(self, mock_create):
        mock_create.return_value = MagicMock()
        build_deep_research_agent(MagicMock(), data_source="wfp")
        system_prompt = mock_create.call_args.kwargs["system_prompt"]
        assert INTRO_MARKER not in system_prompt
        assert HEADING_RULE in system_prompt


class TestReviseIntroductionRules:
    def _render(self, **kwargs):
        return _brief_revise_user_template.render(
            instruction="Tighten it.", content="Some text [1].", **kwargs
        )

    def test_an_introduction_revision_keeps_it_an_introduction(self):
        prompt = self._render(intro_sub_sections=SUBS)
        assert (
            "introduction to a heading whose detail is covered by its sub-sections"
            in prompt
        )
        for sub in SUBS:
            assert f"- {sub}" in prompt
        assert "no headings of any level" in prompt

    def test_other_revisions_are_unchanged(self):
        assert "sub-sections" not in self._render(intro_sub_sections=[])
        assert "sub-sections" not in self._render()


class TestRequestSchemas:
    def test_chat_request_accepts_sub_sections(self):
        req = AssistantChatRequest(query="q", introduces_sub_sections=SUBS)
        assert req.introduces_sub_sections == SUBS

    def test_chat_request_defaults_to_no_sub_sections(self):
        assert AssistantChatRequest(query="q").introduces_sub_sections is None

    @pytest.mark.parametrize("bad", [[], [""], ["x" * 501], ["h"] * 51])
    def test_chat_request_rejects_empty_or_oversized_lists(self, bad):
        with pytest.raises(ValidationError):
            AssistantChatRequest(query="q", introduces_sub_sections=bad)

    def test_revise_request_accepts_sub_sections(self):
        req = BriefReviseRequest(
            content="c",
            instruction="i",
            data_source="wfp",
            introduces_sub_sections=SUBS,
        )
        assert req.introduces_sub_sections == SUBS
