"""Unit tests for the deep-research answer length target (``target_words``).

The Brief tab asks for sections of about N words. That target must (1) reach
the writer prompt as a firm length rule in place of the default
paragraph guidance, and (2) raise the token ceiling so a long target
is not silently truncated.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment, FileSystemLoader

from ui.backend.services.assistant_graph import build_research_agent
from ui.backend.services.assistant_service import (
    TARGET_LENGTH_HEADROOM_TOKENS,
    TOKENS_PER_WORD,
    max_tokens_for_target,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_LENGTH_RULE = "Develop at least three paragraphs"


@pytest.fixture
def jinja_env():
    return Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


@pytest.mark.unit
class TestMaxTokensForTarget:
    def test_no_target_leaves_the_ceiling_alone(self):
        assert max_tokens_for_target(2000, None) == 2000
        assert max_tokens_for_target(None, None) is None

    def test_small_target_never_lowers_the_ceiling(self):
        # 150 words needs far fewer than 2000 tokens; the prompt (not the
        # ceiling) enforces a short answer, so the configured value stands.
        assert max_tokens_for_target(2000, 150) == 2000

    def test_long_target_raises_the_ceiling_to_fit(self):
        needed = int(1500 * TOKENS_PER_WORD + 0.999) + TARGET_LENGTH_HEADROOM_TOKENS
        assert max_tokens_for_target(2000, 1500) == needed
        assert needed > 2000

    def test_unconfigured_ceiling_becomes_what_the_target_needs(self):
        assert max_tokens_for_target(None, 700) == 1120 + TARGET_LENGTH_HEADROOM_TOKENS


@pytest.mark.unit
class TestCoordinatorPromptLengthRule:
    def test_without_a_target_the_default_rule_stands(self, jinja_env):
        result = jinja_env.get_template("assistant_system.j2").render(
            deep_research=True
        )
        assert DEFAULT_LENGTH_RULE in result
        assert "FIRM TARGET" not in result
        assert "Use Markdown headings for a longer answer" in result

    def test_with_a_target_the_default_rule_is_replaced(self, jinja_env):
        result = jinja_env.get_template("assistant_system.j2").render(target_words=350)
        assert DEFAULT_LENGTH_RULE not in result
        assert "approximately 350 words" in result
        # 80%-120% band, integer bounds.
        assert "between 280 and 420" in result
        # A mid-length target keeps headings but fewer, denser paragraphs.
        assert "Aim for approximately" in result
        assert "Use Markdown headings for a longer answer" not in result

    def test_short_target_asks_for_no_headings(self, jinja_env):
        result = jinja_env.get_template("assistant_system.j2").render(target_words=150)
        assert "one or two tight paragraphs and no headings" in result


@pytest.mark.unit
class TestBuildDeepResearchAgentTargetWords:
    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_target_reaches_the_coordinator_system_prompt(self, mock_create):
        mock_create.return_value = MagicMock()
        build_research_agent(
            MagicMock(), data_source="wfp", deep_research=True, target_words=300
        )
        system_prompt = mock_create.call_args.args[3]
        assert "approximately 300 words" in system_prompt
        assert DEFAULT_LENGTH_RULE not in system_prompt

    @patch("ui.backend.services.assistant_graph.build_research_workflow")
    def test_no_target_keeps_the_default_rule(self, mock_create):
        mock_create.return_value = MagicMock()
        build_research_agent(MagicMock(), data_source="wfp", deep_research=True)
        assert DEFAULT_LENGTH_RULE in mock_create.call_args.args[3]
