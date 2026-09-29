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
    BriefTemplateUpdate,
    BriefUpdate,
    VoiceProfileCreate,
    VoiceProfileUpdate,
)
from ui.backend.routes.brief_central import _to_list_item
from ui.backend.routes.brief_library import (
    _copy_name,
    _headings_json,
    _template_read,
    _voice_ids,
)
from ui.backend.services.brief_sharing import owner_name

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

    def test_heading_prompt_voice_and_length_default_to_unset(self):
        heading = BriefTemplateHeading(title="Findings")
        assert (heading.prompt, heading.voice_profile_id, heading.target_words) == (
            None,
            None,
            None,
        )

    def test_heading_prompt_capped_like_section_guidance(self):
        BriefTemplateHeading(title="Ok", prompt="x" * 2000)
        with pytest.raises(ValidationError):
            BriefTemplateHeading(title="Too long", prompt="x" * 2001)

    @pytest.mark.parametrize("words", [49, 5001])
    def test_length_target_bounded(self, words):
        with pytest.raises(ValidationError):
            BriefTemplateHeading(title="H", target_words=words)
        with pytest.raises(ValidationError):
            BriefTemplateCreate(
                name="N", headings=[BriefTemplateHeading(title="H")], target_words=words
            )

    def test_whole_brief_prompt_capped(self):
        with pytest.raises(ValidationError):
            BriefTemplateCreate(
                name="N", headings=[BriefTemplateHeading(title="H")], prompt="x" * 2001
            )

    def test_update_tells_cleared_fields_from_omitted_ones(self):
        cleared = BriefTemplateUpdate(prompt=None, target_words=None)
        omitted = BriefTemplateUpdate(name="Renamed")
        assert {"prompt", "target_words"} <= cleared.model_fields_set
        assert "prompt" not in omitted.model_fields_set


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
        assert owner_name(_FakeUser("Priya Raman", "p@x.org")) == "Priya Raman"

    def test_owner_name_falls_back_to_email(self):
        assert owner_name(_FakeUser(None, "p@x.org")) == "p@x.org"

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


class _FakeTemplate:
    """A brief_templates row as stored before prompts and defaults existed."""

    def __init__(self, headings):
        self.id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.name = "Old template"
        self.description = None
        self.headings = headings
        self.with_text = False
        self.prompt = None
        self.voice_profile_id = None
        self.target_words = None
        self.use_count = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class TestLibraryHelpers:
    """Pure helpers in routes/brief_library.py."""

    def test_voice_ids_collects_template_and_heading_voices(self):
        brief_voice, section_voice = uuid.uuid4(), uuid.uuid4()
        headings = _headings_json(
            [
                BriefTemplateHeading(title="A", voice_profile_id=section_voice),
                BriefTemplateHeading(title="B"),
            ]
        )
        assert _voice_ids(headings, brief_voice) == {brief_voice, section_voice}

    def test_voice_ids_empty_when_none_named(self):
        assert _voice_ids([{"title": "A", "sub": False}], None) == set()

    def test_headings_are_stored_as_plain_json(self):
        voice = uuid.uuid4()
        stored = _headings_json(
            [BriefTemplateHeading(title="A", voice_profile_id=voice)]
        )
        assert stored[0]["voice_profile_id"] == str(voice)

    def test_copy_name_prefixes_and_fits_the_column(self):
        assert _copy_name("Donor memo") == "Copy of Donor memo"
        assert len(_copy_name("x" * 255)) == 255

    def test_template_saved_before_prompts_still_reads(self):
        old = _FakeTemplate([{"title": "Context", "sub": False, "text": None}])
        read = _template_read(old, True, None, 3)
        assert read.headings[0].prompt is None
        assert (read.use_count, read.share_count, read.owner_name) == (0, 3, None)

    def test_shared_template_names_owner_and_hides_share_count(self):
        read = _template_read(_FakeTemplate([{"title": "A"}]), False, "Priya", 5)
        assert (read.can_edit, read.owner_name, read.share_count) == (False, "Priya", 0)


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
