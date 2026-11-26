"""Tests for the Assistant's planning and writing prompts."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
pytestmark = pytest.mark.unit


@pytest.fixture
def prompts():
    return Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=True)


def test_writer_uses_numbered_evidence_and_the_collection(prompts):
    writer = prompts.get_template("assistant_system.j2")
    assert "evaluation collection" in writer.render()
    result = writer.render(data_source="World Bank Reports")
    assert "World Bank Reports" in result
    assert "Cite each factual sentence" in result
    assert "individual numbers in place of citation ranges" in result
    assert "Do not add a References section or a closing recap" in result


def test_planner_explains_when_to_continue_or_stop(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    normal = planner.render()
    assert '"queries"' in normal
    assert "Give an empty list" in normal
    assert "concrete gap, contradiction or limitation" in normal


def test_deep_research_instructs_both_stages_to_check_conflicts(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    assert "corroboration" not in planner.render()
    assert "corroboration" in planner.render(deep_research=True)
    writer = prompts.get_template("assistant_system.j2")
    assert "material disagreement" in writer.render(deep_research=True)


def test_opening_asks_for_each_named_outcome_as_a_stream(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    opening = planner.render(organize=True)
    assert "Keep named outcomes separate" in opening
    assert '"streams"' in opening
    assert "coverage, effectiveness, cost-efficiency and sustainability" in opening
