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


@pytest.mark.parametrize(
    "topic,rows", [("", {}), ("topic", {}), ("topic", {"bad": {"active": True}})]
)
def test_selection_requires_a_topic_and_a_real_template_id(topic, rows):
    with pytest.raises(TemplateSelectionError):
        selected_templates({"brief_topic": topic}, {"cases": rows})


@pytest.mark.asyncio
async def test_deleted_template_is_reported():
    session = SimpleNamespace(scalars=AsyncMock(return_value=[]))
    with pytest.raises(TemplateSelectionError, match="deleted"):
        await read_selected_templates(
            session,
            {"brief_topic": "Example"},
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
    checks = [
        {"type": "brief_intro_scope"},
        {"type": "brief_overlap"},
        {"type": "brief_length"},
    ]
    first = TemplateSection(t, "Pensions", headings, outline, voices, 0, None, 100)
    case, prompt = first.assignment()
    assert (
        case.target_words == 100
        and case.voice_profile == first_voice
        and case.children[0].title == "Exposure"
    )
    assert first.applicable_checks(checks) == [checks[0], checks[2]]
    out = {
        "actual_output": {
            "written": True,
            "summary": "The review found unequal exposure.",
        }
    }
    first.record(out)
    second = TemplateSection(t, "Pensions", headings, outline, voices, 1, None, 100)
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
    assert second.applicable_checks(checks) == checks[1:]
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
