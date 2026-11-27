"""Resolve selected Brief Central templates into sections for a single evaluation run."""

import json
import logging
from dataclasses import dataclass
from itertools import takewhile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from pipeline.db.config import get_application_config
from ui.backend.auth.models import BriefTemplate, VoiceProfile
from ui.backend.auth.schemas import (
    BriefOutlineSection,
    BriefSectionPrompt,
    BriefTemplateHeading,
)
from ui.backend.schemas.testing import BriefCase, BriefCaseVoice
from ui.backend.services.brief_outline_numbers import outline_numbers

DEFAULT_BRIEF_EXPECTATIONS = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "prompts"
        / "brief_evaluation_defaults.json"
    ).read_text()
)


def brief_expectation_matrix(matrix):
    """Apply the standard checks to an experiment created with no columns."""
    if columns := matrix.get("columns"):
        if any(
            row.get("active") and not any(row.get("cols", [])[: len(columns)])
            for row in matrix.get("cases", {}).values()
        ):
            raise TemplateSelectionError(
                "Select at least one expectation for every selected Brief template."
            )
        return matrix
    return {
        "columns": DEFAULT_BRIEF_EXPECTATIONS,
        "cases": {
            key: {**row, "cols": [True] * len(DEFAULT_BRIEF_EXPECTATIONS)}
            for key, row in matrix.get("cases", {}).items()
        },
    }


async def grade_template_checks(output, assertions, judge_factory):
    """Keep independent grades when one check cannot return a valid judgement."""
    from ui.backend.services.brief_grading_errors import grading_error_reason
    from ui.backend.services.test_evaluators import evaluate_assertion

    results = []
    for assertion in assertions:
        try:
            judge = await judge_factory(output, [assertion]) if judge_factory else None
            results.append(evaluate_assertion(assertion, output, judge_fn=judge))
        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Brief expectation %s errored", assertion["type"]
            )
            results.append(
                {
                    **assertion,
                    "error": True,
                    "message": grading_error_reason(exc),
                }
            )
    return results


class TemplateSelectionError(ValueError):
    """An actionable selection error that is safe to display."""


def selected_templates(matrix):
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
    return ids


async def read_selected_templates(session, matrix):
    ids = selected_templates(matrix)
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
    return [templates[k] for k in ids]


@dataclass
class TemplateSection:
    template: BriefTemplate
    headings: list[BriefTemplateHeading]
    outline: list[BriefOutlineSection]
    voices: dict
    position: int
    default_words: int | None
    intro_words: int
    number: str

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
            query=self.template.name,
            heading=heading.title,
            guidance=heading.prompt or "",
            target_words=heading.target_words or default,
            voice_profile=profile,
            children=children,
            siblings=[*self.outline[:i], *self.outline[i + 1 + len(children) :]],
        )
        prompt = BriefSectionPrompt(
            topic=self.template.name,
            current=i,
            outline=self.outline,
            instructions=self.template.prompt,
            focus=heading.prompt,
            voice_instructions=profile.instructions if profile else None,
        )
        return case, prompt

    def inapplicable_checks(self):
        case, _ = self.assignment()
        reasons = {}
        if not case.children:
            reasons["brief_intro_scope"] = (
                "This section has no subheadings to introduce."
            )
        if not case.target_words:
            reasons["brief_length"] = "This section has no word target."
        if not any(s.content for s in (*case.siblings, *case.children)):
            reasons["brief_overlap"] = (
                "There are no other written sections to compare yet."
            )
        return reasons

    async def evaluate(self, assertions, runner, judge_factory):
        from ui.backend.services.test_runner import evaluate_case

        reasons = self.inapplicable_checks()
        applicable = [a for a in assertions if a["type"] not in reasons]
        outcome = await evaluate_case(self, applicable, runner, judge_factory)
        if outcome["assertion_results"] is None:
            outcome["assertion_results"] = [
                {
                    **a,
                    "not_run": True,
                    "message": "Generation failed before this check could run.",
                }
                for a in applicable
            ]
        if assertions:
            graded = iter(outcome["assertion_results"])
            ordered = [
                (
                    {
                        "type": a["type"],
                        "applicable": False,
                        "message": reasons[a["type"]],
                    }
                    if a["type"] in reasons
                    else next(graded)
                )
                for a in assertions
            ]
            outcome["assertion_results"] = [*ordered, *graded]
        self.record(outcome)
        return outcome

    def record(self, outcome):
        output = outcome.get("actual_output") or {}
        case, section = self.assignment()
        assignment = output.setdefault("assignment", {})
        assignment.update(
            template_id=str(self.template.id),
            template_name=self.template.name,
            section_index=self.position,
            heading_number=self.number,
            topic=self.template.name,
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

    templates = await read_selected_templates(session, matrix)
    matrix = brief_expectation_matrix(matrix)
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
        for i, number in enumerate(outline_numbers(h.sub for h in group)):
            plan.append(
                (
                    TemplateSection(
                        template,
                        group,
                        outline,
                        voices,
                        i,
                        config.get("brief_target_words"),
                        intro_words,
                        number,
                    ),
                    assertions,
                )
            )
    return plan
