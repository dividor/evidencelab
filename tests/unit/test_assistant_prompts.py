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
    assert "give an empty list when the evidence addresses the inquiry" in normal
    assert "concrete gap, contradiction or limitation" in normal


@pytest.mark.parametrize("stage", [{}, {"organize": True}, {"contextualize": True}])
def test_geography_guidance_is_shared_and_editable_in_all_planning_stages(
    prompts, stage
):
    planner = prompts.get_template("assistant_research_planner.j2")
    default = planner.render(**stage)
    assert (
        "Keep any country, region or geographic comparison the user requests" in default
    )
    assert "A location mentioned in a result or earlier assistant answer" in default
    assert "Explain that evidence gap." in default
    edited = planner.render(
        instructions="Compare delivery settings by country.", **stage
    )
    assert "Compare delivery settings by country." in edited
    assert "A location mentioned in a result" not in edited


def test_contextualizer_supports_clarification_and_refusal_without_free_text(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    default = planner.render(contextualize=True)
    assert "Clarify ambiguous research requests" in default
    assert "if it could be covered by the selected dataset" in default
    assert '{"action":"clarify"}' in default
    assert '{"action":"decline"}' in default
    edited = planner.render(
        contextualize=True, instructions="Research every follow-up."
    )
    assert "Research every follow-up." in edited
    assert "Clarify ambiguous research requests" not in edited
    assert '{"action":"decline"}' in edited


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


def test_custom_instructions_replace_editable_defaults_and_keep_workflow_rules(prompts):
    planner = prompts.get_template("assistant_research_planner.j2").render(
        organize=True, instructions="Look for implementation barriers first."
    )
    assert "Look for implementation barriers first." in planner
    assert "Keep named outcomes separate" in planner
    assert 'return a JSON object with "queries"' in planner
    assert "concrete gap" not in planner
    writer = prompts.get_template("assistant_system.j2").render(
        instructions="Group findings by evaluation context."
    )
    assert "Group findings by evaluation context." in writer
    assert "Synthesize across relevant passages" not in writer
    assert "Use country examples" not in writer
    assert "Cite each factual sentence" in writer
    assert (
        "Use country examples" in prompts.get_template("assistant_system.j2").render()
    )
