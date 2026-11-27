from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ui.backend.auth.schemas import BriefOutlineSection, BriefTemplateHeading
from ui.backend.schemas.testing import BriefCaseVoice
from ui.backend.services.brief_template_evaluation import (
    TemplateSection,
    TemplateSelectionError,
    read_selected_templates,
    selected_templates,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("rows", [{}, {"bad": {"active": True}}])
def test_selection_requires_valid_template_ids(rows):
    with pytest.raises(TemplateSelectionError):
        selected_templates({"cases": rows})


def test_selection_accepts_a_template_without_a_topic():
    selected = uuid4()
    assert selected_templates({"cases": {str(selected): {"active": True}}}) == [
        selected
    ]


@pytest.mark.asyncio
async def test_deleted_template_is_reported():
    session = SimpleNamespace(scalars=AsyncMock(return_value=[]))
    with pytest.raises(TemplateSelectionError, match="deleted"):
        await read_selected_templates(
            session,
            {"cases": {str(uuid4()): {"active": True}}},
        )


def test_template_section_combines_instructions_inherits_style_and_compares_written_siblings():
    first_voice = BriefCaseVoice(
        id=uuid4(), name="Board", instructions="Use short sentences."
    )
    second_voice = BriefCaseVoice(
        id=uuid4(), name="Staff", instructions="Use direct address."
    )
    t = SimpleNamespace(
        id=uuid4(),
        name="Investment review",
        prompt="Assess the risks.",
        voice_profile_id=first_voice.id,
        target_words=250,
    )
    headings = [
        BriefTemplateHeading(title="Overview"),
        BriefTemplateHeading(
            title="Exposure",
            sub=True,
            prompt="Compare terms.",
            voice_profile_id=second_voice.id,
            target_words=170,
        ),
    ]
    outline = [
        BriefOutlineSection(title=h.title, level=2 if h.sub else 1) for h in headings
    ]
    voices = {v.id: v for v in (first_voice, second_voice)}
    first = TemplateSection(t, headings, outline, voices, 0, None, 100, "1")
    case, prompt = first.assignment()
    assert (
        case.target_words == 100
        and case.voice_profile == first_voice
        and case.children[0].title == "Exposure"
    )
    assert set(first.inapplicable_checks()) == {"brief_overlap"}
    out = {
        "actual_output": {
            "written": True,
            "summary": "The review found unequal exposure.",
        }
    }
    first.record(out)
    second = TemplateSection(t, headings, outline, voices, 1, None, 100, "1.1")
    case, prompt = second.assignment()
    assert (
        case.target_words == 170
        and case.children == []
        and case.voice_profile == second_voice
    )
    assert (
        prompt.current,
        prompt.instructions,
        prompt.focus,
        prompt.voice_instructions,
    ) == (1, t.prompt, "Compare terms.", second_voice.instructions)
    assert prompt.outline[0].content == out["actual_output"]["summary"]
    assert set(second.inapplicable_checks()) == {"brief_intro_scope"}
    assert out["actual_output"]["assignment"]["template_id"] == str(t.id)
    failed = {"actual_output": None}
    second.record(failed)
    assert failed["actual_output"]["assignment"]["heading"] == "Exposure"
    assert outline[1].content is None


def test_evaluation_template_list_edit_and_voices_require_admin():
    from inspect import signature

    from ui.backend.auth.users import current_superuser
    from ui.backend.routes import brief_library

    for route in (
        brief_library.evaluation_template,
        brief_library.evaluation_templates,
        brief_library.edit_evaluation_template,
        brief_library.evaluation_template_voices,
    ):
        assert (
            signature(route).parameters["admin"].default.dependency is current_superuser
        )


def test_empty_experiment_gets_all_standard_checks_and_custom_matrix_is_preserved():
    from ui.backend.services.brief_template_evaluation import brief_expectation_matrix

    initial = {"columns": [], "cases": {"template": {"active": True, "cols": []}}}
    defaults = brief_expectation_matrix(initial)
    assert {a["type"] for a in defaults["columns"]} == {
        "brief_structure",
        "brief_length",
        "brief_overlap",
        "brief_intro_scope",
        "brief_factual",
        "llm_judge",
        "brief_voice",
        "brief_writing",
        "brief_paragraphs",
    }
    assert defaults["cases"]["template"]["cols"] == [True] * 9
    assert brief_expectation_matrix(defaults) == defaults
    assert initial["columns"] == []
    with pytest.raises(TemplateSelectionError, match="one expectation"):
        brief_expectation_matrix({**initial, "columns": [{"type": "brief_structure"}]})


@pytest.mark.asyncio
async def test_grading_error_keeps_the_other_checks():
    from ui.backend.services.brief_template_evaluation import grade_template_checks

    async def judge(output, assertions):
        if assertions[0]["type"] == "brief_writing":
            raise ValueError("Malformed reply")

    results = await grade_template_checks(
        {"capability": "brief", "assignment": {}},
        [{"type": "brief_writing", "label": "Flow"}, {"type": "brief_voice"}],
        judge,
    )
    assert results[0]["error"] and results[0]["label"] == "Flow"
    assert results[1]["passed"]


def test_historical_section_numbers_use_saved_levels_and_child_headings():
    from ui.backend.services.brief_outline_numbers import (
        number_saved_sections,
        outline_numbers,
    )

    assert outline_numbers([True, True, False, True, True]) == [
        "1",
        "1.1",
        "2",
        "2.1",
        "2.2",
    ]
    rows = [
        SimpleNamespace(
            actual_output={
                "assignment": {
                    "template_id": "t",
                    "section_index": 0,
                    "child_headings": ["Notes"],
                },
                "siblings": [{"level": 1}, {"level": 2}],
            }
        ),
        SimpleNamespace(
            actual_output={"assignment": {"template_id": "t", "section_index": 1}}
        ),
        SimpleNamespace(
            actual_output={"assignment": {"template_id": "t", "section_index": 2}}
        ),
    ]
    number_saved_sections(rows)
    assert [r.actual_output["assignment"]["heading_number"] for r in rows] == [
        "1",
        "1.1",
        "2",
    ]
