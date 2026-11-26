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
    assert "document collection" in writer.render()
    result = writer.render(data_source="World Bank Reports")
    assert "World Bank Reports" in result
    assert "Cite each factual sentence" in result
    assert "individual numbers in place of citation ranges" in result
    assert "Do not add a References section or a closing recap" in result


def test_planner_explains_when_to_continue_or_stop(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    normal = planner.render()
    assert '"queries"' in normal
    assert "Stop when the evidence directly answers the inquiry" in normal
    assert "concrete gap, contradiction or limitation" in normal


def test_grounding_uses_report_title_to_verify_location_and_passage_to_verify_claim(
    prompts,
):
    reviewer = prompts.get_template("assistant_grounding_check.j2").render(
        brief_section=True
    )
    assert "verify that detail against the\nsource title or passage" in reviewer
    assert "does not establish the named setting or another" in reviewer
    assert "reject a sentence about a different group or setting" in reviewer
    assert "Use the passage itself to verify the finding" in reviewer


def test_brief_prose_review_accepts_evidence_gap_after_cited_opening(prompts):
    reviewer = prompts.get_template("brief_prose_check.j2").render(system=True)
    assert "Do not request the missing data again" in reviewer
    assert "or require that sentence in the opening" in reviewer


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
    assert '{"action":"decline","next_step":"ask"}' in default
    edited = planner.render(
        contextualize=True, instructions="Research every follow-up."
    )
    assert "Research every follow-up." in edited
    assert "Clarify ambiguous research requests" not in edited
    assert '{"action":"decline","next_step":"ask"}' in edited


def test_brief_section_prompt_preserves_length_and_introduction_rules(prompts):
    writer = prompts.get_template("assistant_system.j2")
    settings = {"brief_section_prompt": "Use plain English.", "target_words": 350}
    result = writer.render(**settings)
    assert "Use plain English." in result
    assert "approximately 350 words" in result
    assert "Use only as many headings" not in result
    brief_default = prompts.get_template("brief_section_instructions.j2").render()
    assert "without an extra title, headings, or subsections" in brief_default
    assert "leave other sections' findings" in brief_default
    assert "organize headings around findings" in writer.render()

    intro = writer.render(**settings, intro_sub_sections=["Financing", "Coverage"])
    assert "without reproducing their findings" in intro
    assert "- Financing" in intro and "- Coverage" in intro
    assert "Keep the introduction to at most about 350 words." in intro


def test_deep_research_instructs_both_stages_to_check_conflicts(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    assert "corroboration" not in planner.render()
    assert "corroboration" in planner.render(deep_research=True)
    writer = prompts.get_template("assistant_system.j2")
    assert "material disagreement" in writer.render(deep_research=True)


def test_opening_asks_for_each_named_outcome_as_a_stream(prompts):
    planner = prompts.get_template("assistant_research_planner.j2")
    opening = planner.render(organize=True)
    assert "separate when there are four or fewer" in opening
    assert '"streams"' in opening
    assert "main part, up to four" in opening


def test_custom_instructions_replace_editable_defaults_and_keep_workflow_rules(prompts):
    planner = prompts.get_template("assistant_research_planner.j2").render(
        organize=True, instructions="Look for implementation barriers first."
    )
    assert "Look for implementation barriers first." in planner
    assert "separate when there are four or fewer" in planner
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
