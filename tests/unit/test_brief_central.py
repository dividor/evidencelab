"""Unit tests for Brief Central schemas, route helpers and prompt injection."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    BriefCreate,
    BriefShareCreate,
    BriefTemplateCreate,
    BriefTemplateHeading,
    BriefUpdate,
    VoiceProfileCreate,
    VoiceProfileUpdate,
)
from ui.backend.routes.brief_central import _owner_name, _to_list_item

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Voice profile schemas
# ---------------------------------------------------------------------------


class TestVoiceProfileSchemas:
    """Validation rules for voice & tone profiles."""

    def test_valid_create(self):
        vp = VoiceProfileCreate(
            name="Policy brief",
            description="Measured register",
            instructions="Write in a measured, evaluative register.",
        )
        assert vp.name == "Policy brief"

    def test_create_requires_name(self):
        with pytest.raises(ValidationError):
            VoiceProfileCreate(name="", instructions="Some instructions")

    def test_create_requires_instructions(self):
        with pytest.raises(ValidationError):
            VoiceProfileCreate(name="Name", instructions="")

    def test_instructions_length_capped(self):
        with pytest.raises(ValidationError):
            VoiceProfileCreate(name="Name", instructions="x" * 10_001)

    def test_update_all_optional(self):
        upd = VoiceProfileUpdate()
        assert upd.name is None
        assert upd.instructions is None


# ---------------------------------------------------------------------------
# Template schemas
# ---------------------------------------------------------------------------


class TestBriefTemplateSchemas:
    """Validation rules for brief templates."""

    def test_valid_create(self):
        tpl = BriefTemplateCreate(
            name="Evaluation synthesis",
            headings=[
                BriefTemplateHeading(title="Context and scope"),
                BriefTemplateHeading(title="Findings", sub=True),
            ],
        )
        assert tpl.with_text is False
        assert tpl.headings[0].sub is False
        assert tpl.headings[1].sub is True

    def test_headings_required_nonempty(self):
        with pytest.raises(ValidationError):
            BriefTemplateCreate(name="Empty", headings=[])

    def test_heading_title_required(self):
        with pytest.raises(ValidationError):
            BriefTemplateCreate(name="Bad", headings=[BriefTemplateHeading(title="")])

    def test_headings_capped_at_100(self):
        headings = [BriefTemplateHeading(title=f"H{i}") for i in range(101)]
        with pytest.raises(ValidationError):
            BriefTemplateCreate(name="Too many", headings=headings)

    def test_heading_text_optional(self):
        heading = BriefTemplateHeading(title="With text", text="Saved draft text.")
        assert heading.text == "Saved draft text."


# ---------------------------------------------------------------------------
# Brief schemas
# ---------------------------------------------------------------------------


class TestBriefSchemas:
    """Validation rules for brief create/update payloads."""

    def test_valid_create(self):
        brief = BriefCreate(
            title="Cash transfers",
            query="Effectiveness of cash",
            data_source="wfp",
            content={"sections": [], "sourceCount": 0},
        )
        assert brief.voice_profile_id is None
        assert brief.content["sections"] == []

    def test_title_required(self):
        with pytest.raises(ValidationError):
            BriefCreate(title="", content={})

    def test_content_size_capped(self):
        # Content shares the saved-research JSONB cap (10 MB serialised).
        with pytest.raises(ValidationError):
            BriefCreate(title="Huge", content={"blob": "x" * 10_000_001})

    def test_update_partial(self):
        upd = BriefUpdate(title="New title")
        assert upd.content is None
        assert upd.voice_profile_id is None

    def test_share_target_required(self):
        with pytest.raises(ValidationError):
            BriefShareCreate(target="")


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, full_name, email):
        self.full_name = full_name
        self.email = email


class _FakeBrief:
    def __init__(self, content):
        self.id = uuid.uuid4()
        self.title = "T"
        self.query = "Q"
        self.data_source = "wfp"
        self.voice_profile_id = None
        self.content = content
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class TestRouteHelpers:
    """Pure helpers in routes/brief_central.py."""

    def test_owner_name_prefers_full_name(self):
        assert _owner_name(_FakeUser("Priya Raman", "p@x.org")) == "Priya Raman"

    def test_owner_name_falls_back_to_email(self):
        assert _owner_name(_FakeUser(None, "p@x.org")) == "p@x.org"

    def test_to_list_item_counts_sections_and_sources(self):
        brief = _FakeBrief({"sections": [{}, {}, {}], "sourceCount": 41})
        item = _to_list_item(brief, "Owner", 2)
        assert item.section_count == 3
        assert item.source_count == 41
        assert item.owner_name == "Owner"
        assert item.share_count == 2

    def test_to_list_item_handles_empty_content(self):
        item = _to_list_item(_FakeBrief({}), None, 0)
        assert item.section_count == 0
        assert item.source_count == 0


# ---------------------------------------------------------------------------
# Voice injection into the revise prompt
# ---------------------------------------------------------------------------


class TestRevisePromptVoiceInjection:
    """The brief_revise_user.j2 template renders voice instructions when given."""

    @staticmethod
    def _render(**kwargs):
        from ui.backend.services.llm_service import _brief_revise_user_template

        return _brief_revise_user_template.render(**kwargs)

    def test_voice_block_present(self):
        prompt = self._render(
            instruction="Tighten the opening.",
            content="Some section text.",
            voice_instructions="Short sentences. Active voice.",
        )
        assert "Voice & tone profile" in prompt
        assert "Short sentences. Active voice." in prompt

    def test_voice_block_absent_when_none(self):
        prompt = self._render(
            instruction="Tighten the opening.",
            content="Some section text.",
            voice_instructions=None,
        )
        assert "Voice & tone profile" not in prompt
