"""Unit tests for assistant prompt templates."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@pytest.fixture
def jinja_env():
    """Jinja2 environment pointed at the prompts directory."""
    return Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


class TestAssistantSystemPrompt:
    """Tests for assistant_system.j2 template."""

    def test_renders_without_data_source(self, jinja_env):
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "research assistant" in result.lower()
        assert "citations" in result.lower()

    def test_renders_with_data_source(self, jinja_env):
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render(data_source="World Bank Reports")
        assert "World Bank Reports" in result

    def test_contains_key_instructions(self, jinja_env):
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "search results" in result.lower()
        assert "markdown" in result.lower()


class TestAssistantPlanPrompt:
    """Tests for assistant_plan.j2 template."""

    def test_renders_with_query(self, jinja_env):
        template = jinja_env.get_template("assistant_plan.j2")
        result = template.render(query="What is food security?")
        assert "What is food security?" in result
        assert "JSON" in result

    def test_renders_with_conversation_context(self, jinja_env):
        template = jinja_env.get_template("assistant_plan.j2")
        result = template.render(
            query="Tell me more",
            conversation_context="User: What is food security?\nAssistant: ...",
        )
        assert "Tell me more" in result
        assert "Previous conversation context" in result

    def test_renders_without_conversation_context(self, jinja_env):
        template = jinja_env.get_template("assistant_plan.j2")
        result = template.render(
            query="What is food security?",
            conversation_context=None,
        )
        assert "What is food security?" in result
        # The conversation context block should NOT render
        assert "Previous conversation context" not in result

    def test_output_format_instructions(self, jinja_env):
        template = jinja_env.get_template("assistant_plan.j2")
        result = template.render(query="test")
        assert "JSON array" in result


class TestAssistantSynthesizePrompt:
    """Tests for assistant_synthesize.j2 template."""

    def test_renders_with_search_results(self, jinja_env):
        template = jinja_env.get_template("assistant_synthesize.j2")
        results = [
            {"title": "Report A", "text": "Finding about food security."},
            {"title": "Report B", "text": "Data on malnutrition rates."},
        ]
        result = template.render(query="food security findings", search_results=results)
        assert "food security findings" in result
        assert "Report A" in result
        assert "Report B" in result
        assert "[1]" in result
        assert "[2]" in result

    def test_renders_without_previous_synthesis(self, jinja_env):
        template = jinja_env.get_template("assistant_synthesize.j2")
        result = template.render(
            query="test",
            search_results=[{"title": "Doc", "text": "Content"}],
            previous_synthesis=None,
        )
        assert "Previous answer" not in result

    def test_renders_with_previous_synthesis(self, jinja_env):
        template = jinja_env.get_template("assistant_synthesize.j2")
        result = template.render(
            query="test",
            search_results=[{"title": "Doc", "text": "Content"}],
            previous_synthesis="Previous answer text here.",
        )
        assert "Previous answer" in result
        assert "Previous answer text here." in result

    def test_citation_instructions(self, jinja_env):
        template = jinja_env.get_template("assistant_synthesize.j2")
        result = template.render(
            query="test",
            search_results=[{"title": "Doc", "text": "Content"}],
        )
        assert "cite" in result.lower()
        assert "inline" in result.lower()


class TestAssistantReflectPrompt:
    """Tests for assistant_reflect.j2 template."""

    def test_renders_with_all_variables(self, jinja_env):
        template = jinja_env.get_template("assistant_reflect.j2")
        result = template.render(
            query="What is food security?",
            synthesis="Food security is...",
            num_results=15,
            iteration=1,
            max_iterations=3,
        )
        assert "What is food security?" in result
        assert "Food security is..." in result
        assert "15" in result
        assert "1" in result
        assert "3" in result

    def test_output_format_instructions(self, jinja_env):
        template = jinja_env.get_template("assistant_reflect.j2")
        result = template.render(
            query="test",
            synthesis="answer",
            num_results=5,
            iteration=1,
            max_iterations=3,
        )
        assert "should_continue" in result
        assert "JSON" in result

    def test_evaluation_criteria(self, jinja_env):
        template = jinja_env.get_template("assistant_reflect.j2")
        result = template.render(
            query="test",
            synthesis="answer",
            num_results=5,
            iteration=1,
            max_iterations=3,
        )
        assert "completeness" in result.lower() or "fully address" in result.lower()
