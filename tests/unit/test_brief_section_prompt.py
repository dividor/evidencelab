"""Unit tests for the Brief section research prompt the API writes."""

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    BRIEF_PROMPT_MAX_CHARS,
    BRIEF_RUN_CONTENT_MAX_CHARS,
    VOICE_INSTRUCTIONS_MAX_CHARS,
    AssistantChatRequest,
    BriefSectionPrompt,
)
from ui.backend.services.brief_section_prompt import (
    build_section_prompt,
    outline_context,
)

OUTLINE = [
    {"title": "Context and scope", "level": 1},
    {
        "title": "What the evidence shows",
        "level": 1,
        "content": "# What the evidence shows\n\nCash transfers improved food "
        "consumption [1].",
    },
    {"title": "Effectiveness", "level": 1},
    {"title": "Cost efficiency", "level": 2},
    {"title": "Outcomes", "level": 2},
]


def _prompt(current=0, outline=None, **parts) -> str:
    return build_section_prompt(
        BriefSectionPrompt(
            outline=outline if outline is not None else OUTLINE,
            current=current,
            **parts,
        )
    )


def _context(current: int, outline=None) -> str:
    return outline_context(
        BriefSectionPrompt(outline=outline or OUTLINE, current=current).outline,
        current,
    )


@pytest.mark.unit
class TestBuildSectionPrompt:
    def test_prompt_when_topic_set_then_names_section_and_topic(self):
        prompt = _prompt(0, topic="girls education in Kenya")
        assert '"Context and scope"' in prompt
        assert 'on "girls education in Kenya"' in prompt
        assert "Search the document library" in prompt

    def test_prompt_when_sub_section_then_scoped_to_parent_heading(self):
        prompt = _prompt(4, topic="cash")
        assert 'parent section "Effectiveness"' in prompt
        assert "avoid repeating material that belongs in sibling sections" in prompt

    def test_prompt_when_top_level_section_then_no_parent(self):
        assert "parent section" not in _prompt(2)

    def test_prompt_when_guidance_and_focus_then_both_included(self):
        prompt = _prompt(
            0,
            topic="girls education in Kenya",
            instructions="prioritise RCTs since 2018",
            focus="emphasise rural areas",
        )
        assert "Overall brief guidance: prioritise RCTs since 2018" in prompt
        assert "Focus for this section: emphasise rural areas" in prompt

    def test_prompt_when_single_section_without_topic_then_exact_text(self):
        prompt = _prompt(0, outline=[{"title": "Background", "level": 1}])
        assert prompt == (
            'Write the "Background" section of an evidence brief. '
            "Search the document library for evidence relevant to this specific "
            "section and cite a source for every claim. "
            "Your final answer must be the finished section text itself — never "
            "a description of what you are about to do, a promise to research, "
            "or narration of your process."
        )

    def test_prompt_when_update_then_keeps_draft_and_dates_search(self):
        prompt = _prompt(
            1,
            topic="girls education",
            mode="update",
            draft="Enrolment rose sharply [1].",
            instruction="prioritise enforcement",
            published_after="2023-05-01T00:00:00.000Z",
        )
        assert "Enrolment rose sharply [1]." in prompt
        assert "Preserve its wording, structure and citations" in prompt
        assert "PUBLISHED AFTER 2023-05-01 " in prompt
        assert "Additional instruction: prioritise enforcement" in prompt
        assert "sequential [n] citation markers" in prompt

    def test_prompt_when_update_without_draft_then_writes_section(self):
        prompt = _prompt(1, mode="update")
        assert 'Write the "What the evidence shows" section' in prompt
        assert "Preserve its wording" not in prompt

    def test_prompt_when_outline_then_follows_the_section_instructions(self):
        prompt = _prompt(2, topic="cash transfers")
        assert prompt.index("Write") < prompt.index("full outline of the brief")

    def test_prompt_when_voice_then_ends_with_voice_profile(self):
        prompt = _prompt(0, voice_instructions="Plain, short sentences.")
        assert prompt.endswith(
            "Voice & tone profile — write the section in this style: "
            "Plain, short sentences."
        )


@pytest.mark.unit
class TestOutlineContext:
    def test_context_when_writing_a_section_then_lists_and_marks_it(self):
        ctx = _context(0)
        assert "Context and scope ← the section you are writing" in ctx
        assert "- What the evidence shows" in ctx
        assert "  - Cost efficiency" in ctx
        assert "do NOT repeat or pre-empt material" in ctx

    def test_context_when_section_written_then_gist_without_markup(self):
        ctx = _context(0)
        assert (
            "already written; covers: What the evidence shows Cash transfers "
            "improved food consumption" in ctx
        )
        assert "[1]" not in ctx
        assert "#" not in ctx

    def test_context_when_written_section_is_long_then_gist_is_cut(self):
        outline = [
            {"title": "A", "level": 1},
            {"title": "B", "level": 1, "content": "word " * 100},
        ]
        gist = _context(0, outline).split("covers: ")[1].split(")")[0]
        assert gist.startswith("word word")
        assert gist.endswith("…")
        assert len(gist) == 180 + len("…")

    def test_context_when_heading_has_sub_sections_then_asks_for_introduction(self):
        ctx = _context(2)
        assert "sub-sections (Cost efficiency; Outcomes)" in ctx
        assert "high-level introduction" in ctx

    def test_context_when_sub_section_or_leaf_then_no_introduction_rule(self):
        assert "high-level introduction" not in _context(3)
        assert "high-level introduction" not in _context(0)

    def test_context_when_single_section_then_empty(self):
        assert _context(0, [OUTLINE[0]]) == ""


@pytest.mark.unit
class TestBriefSectionPromptSchema:
    def test_schema_when_current_outside_outline_then_rejected(self):
        with pytest.raises(ValidationError):
            BriefSectionPrompt(outline=OUTLINE, current=len(OUTLINE))

    def test_schema_when_outline_empty_then_rejected(self):
        with pytest.raises(ValidationError):
            BriefSectionPrompt(outline=[], current=0)

    def test_schema_when_heading_empty_then_accepted(self):
        prompt = _prompt(0, outline=[{"title": "", "level": 1}])
        assert 'Write the "" section' in prompt

    def test_schema_when_long_update_draft_then_accepted(self):
        """A section draft is limited like a stored run, not like a question."""
        draft = "x" * BRIEF_RUN_CONTENT_MAX_CHARS
        prompt = _prompt(0, mode="update", draft=draft)
        assert draft in prompt

    @pytest.mark.parametrize(
        "parts",
        [
            {"draft": "x" * (BRIEF_RUN_CONTENT_MAX_CHARS + 1)},
            {"voice_instructions": "x" * (VOICE_INSTRUCTIONS_MAX_CHARS + 1)},
            {"instructions": "x" * (BRIEF_PROMPT_MAX_CHARS + 1)},
            {"focus": "x" * (BRIEF_PROMPT_MAX_CHARS + 1)},
            {"instruction": "x" * (BRIEF_PROMPT_MAX_CHARS + 1)},
            {"outline": [{"title": "t", "level": 1}] * 101},
            {"outline": [{"title": "t" * 501, "level": 1}]},
            {"outline": [{"title": "t", "level": 3}]},
            {"mode": "edit"},
        ],
    )
    def test_schema_when_part_over_its_limit_then_rejected(self, parts):
        fields = {"outline": OUTLINE, "current": 0, **parts}
        with pytest.raises(ValidationError):
            BriefSectionPrompt(**fields)

    def test_chat_request_when_brief_section_then_question_stays_capped(self):
        """The brief's parts do not widen the chat question's own limit."""
        section = {"outline": OUTLINE, "current": 0, "draft": "x" * 50_000}
        request = AssistantChatRequest(query="Heading", brief_section=section)
        assert request.brief_section is not None
        with pytest.raises(ValidationError):
            AssistantChatRequest(query="x" * 5001, brief_section=section)
