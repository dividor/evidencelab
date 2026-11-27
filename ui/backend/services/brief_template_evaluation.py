"""Resolve selected Brief Central templates into sections for a single evaluation run."""

from dataclasses import dataclass
from itertools import takewhile
from uuid import UUID

from sqlalchemy import select

from pipeline.db.config import get_application_config
from ui.backend.auth.models import BriefTemplate, VoiceProfile
from ui.backend.auth.schemas import (
    BRIEF_TOPIC_MAX_CHARS,
    BriefOutlineSection,
    BriefSectionPrompt,
    BriefTemplateHeading,
)
from ui.backend.schemas.testing import BriefCase, BriefCaseVoice


class TemplateSelectionError(ValueError):
    """An actionable selection error that is safe to display."""


def selected_templates(config, matrix):
    topic = (config or {}).get("brief_topic")
    if (
        not isinstance(topic, str)
        or not 0 < len(topic.strip()) <= BRIEF_TOPIC_MAX_CHARS
    ):
        raise TemplateSelectionError(
            f"Enter a brief topic of up to {BRIEF_TOPIC_MAX_CHARS} characters."
        )
    try:
        ids = [
            UUID(key) for key, row in matrix["cases"].items() if row["active"] is True
        ]
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise TemplateSelectionError(
            "Choose valid templates for this experiment."
        ) from exc
    if not ids:
        raise TemplateSelectionError("Choose at least one brief template.")
    return topic.strip(), ids


async def read_selected_templates(session, config, matrix):
    topic, ids = selected_templates(config, matrix)
    templates = {
        t.id: t
        for t in await session.scalars(
            select(BriefTemplate).where(BriefTemplate.id.in_(ids))
        )
    }
    if len(templates) != len(ids):
        raise TemplateSelectionError(
            "A selected template was deleted. Edit the experiment and choose its templates again."
        )
    return topic, [templates[k] for k in ids]


@dataclass
class TemplateSection:
    template: BriefTemplate
    topic: str
    headings: list[BriefTemplateHeading]
    outline: list[BriefOutlineSection]
    voices: dict
    position: int
    default_words: int | None
    intro_words: int

    def assignment(self):
        i = self.position
        heading = self.headings[i]
        children = (
            []
            if heading.sub
            else list(takewhile(lambda s: s.level == 2, self.outline[i + 1 :]))
        )
        brief_words = self.template.target_words or self.default_words
        default = (
            min(brief_words or self.intro_words, self.intro_words)
            if children
            else brief_words
        )
        voice_id = heading.voice_profile_id or self.template.voice_profile_id
        profile = self.voices[voice_id] if voice_id else None
        case = BriefCase(
            query=self.topic,
            heading=heading.title,
            guidance=heading.prompt or "",
            target_words=heading.target_words or default,
            voice_profile=profile,
            children=children,
            siblings=[*self.outline[:i], *self.outline[i + 1 + len(children) :]],
        )
        prompt = BriefSectionPrompt(
            topic=self.topic,
            current=i,
            outline=self.outline,
            instructions=self.template.prompt,
            focus=heading.prompt,
            voice_instructions=profile.instructions if profile else None,
        )
        return case, prompt

    def applicable_checks(self, assertions):
        case, _ = self.assignment()
        applicable = {
            "brief_intro_scope": bool(case.children),
            "brief_length": case.target_words is not None,
            "brief_overlap": any(s.content for s in (*case.siblings, *case.children)),
        }
        return [check for check in assertions if applicable.get(check["type"], True)]

    def record(self, outcome):
        output = outcome.get("actual_output") or {}
        case, section = self.assignment()
        assignment = output.setdefault("assignment", {})
        assignment.update(
            template_id=str(self.template.id),
            template_name=self.template.name,
            section_index=self.position,
            topic=self.topic,
            heading=case.heading,
            instructions=section.instructions,
            guidance=case.guidance,
            target_words=case.target_words,
            voice_profile=(
                case.voice_profile.model_dump(mode="json")
                if case.voice_profile
                else None
            ),
        )
        if output.get("written"):
            self.outline[self.position] = self.outline[self.position].model_copy(
                update={"content": output["summary"]}
            )
        output.setdefault("capability", "brief")
        outcome["actual_output"] = output


async def template_plan(session, config, matrix):
    from ui.backend.services.test_runner import _resolve_case_plan

    topic, templates = await read_selected_templates(session, config, matrix)
    headings = [
        [BriefTemplateHeading.model_validate(h) for h in t.headings] for t in templates
    ]
    ids = {
        h.voice_profile_id for group in headings for h in group if h.voice_profile_id
    }
    ids.update(t.voice_profile_id for t in templates if t.voice_profile_id)
    voices = {
        p.id: BriefCaseVoice.model_validate(p, from_attributes=True)
        for p in await session.scalars(
            select(VoiceProfile).where(VoiceProfile.id.in_(ids))
        )
    }
    if ids - voices.keys():
        raise TemplateSelectionError(
            "A selected voice profile was deleted. Edit the template to choose a profile."
        )
    intro_words = (
        get_application_config()
        .get("brief", {})
        .get("introductions", {})
        .get("target_words", 120)
    )
    plan = []
    for template, group in zip(templates, headings):
        outline = [
            BriefOutlineSection(
                title=h.title,
                level=2 if h.sub else 1,
                content=h.text if template.with_text else None,
            )
            for h in group
        ]
        _, assertions = _resolve_case_plan(matrix, str(template.id), "brief")
        for i in range(len(group)):
            plan.append(
                (
                    TemplateSection(
                        template,
                        topic,
                        group,
                        outline,
                        voices,
                        i,
                        config.get("brief_target_words"),
                        intro_words,
                    ),
                    assertions,
                )
            )
    return plan
