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

    def test_search_tool_reference(self, jinja_env):
        """System prompt should reference the search tool."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "search_documents" in result.lower()

    def test_citation_instructions(self, jinja_env):
        """System prompt should include citation formatting instructions."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "[1]" in result
        assert "[2]" in result
        assert "inline" in result.lower()

    def test_query_decomposition_instructions(self, jinja_env):
        """System prompt should instruct the agent to decompose complex queries."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "plan" in result.lower()
        assert "sub-quer" in result.lower()

    def test_synthesis_instructions(self, jinja_env):
        """System prompt should instruct the agent to synthesize after searching."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "synthesize" in result.lower()
        assert "stop searching" in result.lower()

    def test_no_references_section(self, jinja_env):
        """System prompt should tell the model not to include references."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "do not include a 'references' section" in result.lower()

    def test_global_numbering_instruction(self, jinja_env):
        """System prompt should mention global numbering."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "global" in result.lower()

    def test_forbids_citation_ranges(self, jinja_env):
        """System prompt should explicitly forbid citation ranges like [1-10]."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "[1-5]" in result
        assert "[1-10]" in result
        assert "list individual numbers explicitly" in result.lower()

    def test_forbids_closing_summary(self, jinja_env):
        """System prompt should forbid conclusion/summary paragraphs."""
        template = jinja_env.get_template("assistant_system.j2")
        result = template.render()
        assert "closing paragraph" in result.lower()
        assert "do not add any paragraph that rounds up" in result.lower()
