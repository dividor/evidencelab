"""Generate an experimental section through the same research service as Brief."""

import re

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, model_validator

from ui.backend.auth.schemas import (
    AssistantSearchSettings,
    BriefOutlineSection,
    BriefSectionPrompt,
)
from ui.backend.schemas.testing import BriefCase
from ui.backend.services.assistant_service import stream_research_response
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.brief_section_prompt import (
    brief_search_query,
    brief_section_prompt_default,
)
from ui.backend.services.citation_fidelity import (
    strip_citation_markers,
    unresolved_numbers,
)
from ui.backend.services.group_settings import CITATION_CHECK_DEFAULT
from ui.backend.services.llm_choice import (
    BRIEF,
    CITATION_CHECK,
    combo_default,
    default_combo,
)
from ui.backend.services.test_evaluators import brief_assertion_type, judge_rubric_key


def configure_brief(config, combo):
    assistant = combo.get("assistant_model") or combo.get("summarization_model") or {}
    assistant = assistant if isinstance(assistant, dict) else {}
    defaults = {
        "brief_model": combo_default(BRIEF, combo),
        "brief_temperature": assistant.get("temperature"),
        "brief_max_tokens": assistant.get("max_tokens"),
        "brief_citation_check": CITATION_CHECK_DEFAULT,
        "citation_model": combo_default(CITATION_CHECK, default_combo()),
        "brief_prompt": brief_section_prompt_default(),
    }
    for key, value in defaults.items():
        config.setdefault(key, value)


def _settings(config):
    from ui.backend.routes.search import _parse_boost_fields, _parse_section_types

    values = {k: config[k] for k in AssistantSearchSettings.model_fields if k in config}
    values.update(
        field_boost_enabled=config["field_boost"],
        field_boost_fields=_parse_boost_fields(config["field_boost_fields"]),
        section_types=_parse_section_types(config["section_types"]),
        rerank_model_page_size=config.get("max_rerank_candidates") or None,
    )
    return AssistantSearchSettings.model_validate(values).model_dump(exclude_none=True)


async def run_brief_case(raw, config, source):
    case = BriefCase.model_validate(raw)
    section = BriefSectionPrompt(
        topic=case.query,
        outline=[
            *case.siblings,
            BriefOutlineSection(title=case.heading),
            *(child.model_copy(update={"level": 2}) for child in case.children),
        ],
        current=len(case.siblings),
        focus=case.guidance,
        voice_instructions=(
            case.voice_profile.instructions if case.voice_profile else case.voice
        ),
    )
    target = case.target_words
    events = stream_research_response(
        query=case.heading,
        data_source=source,
        model_key=config["brief_model"],
        temperature=config.get("brief_temperature"),
        max_tokens=config.get("brief_max_tokens"),
        deep_research=True,
        search_settings=_settings(config),
        reranker_model=config.get("rerank_model") if config["rerank"] else None,
        brief_section=section,
        brief_section_prompt=config["brief_prompt"],
        initial_search_query=brief_search_query(section),
        target_words=target,
        citation_order=False,
        check_citations=config["brief_citation_check"],
        citation_model_key=(
            config["citation_model"] if config["brief_citation_check"] else None
        ),
    )
    out = {
        "capability": "brief",
        "summary": "",
        "sources": [],
        "searches": [],
        "written": False,
        "assignment": dict(
            topic=case.query,
            heading=case.heading,
            child_headings=[child.title for child in case.children],
            guidance=case.guidance,
            voice=section.voice_instructions,
            voice_profile=(
                case.voice_profile.model_dump(mode="json")
                if case.voice_profile
                else None
            ),
            target_words=target,
        ),
        "siblings": [s.model_dump() for s in (*case.siblings, *case.children)],
        "reference_standard": case.reference_standard,
    }
    done = False
    async for event in events:
        kind = event["type"]
        if kind == "error":
            raise RuntimeError("Brief generation failed.")
        if kind == "token":
            out["summary"] = event["token"]
        elif kind == "brief_editorial_review":
            out["editorial_issues"] = event["issues"]
        elif kind == "sources":
            out["sources"] = event["sources"]
        elif kind == "search_status":
            out["searches"].extend(event["queries"])
        elif kind == "done":
            out.update(written=event["section_written"], usage=event.get("usage") or {})
            done = True
    if not done:
        raise RuntimeError("Brief generation ended before completion.")
    out["words"] = len(strip_citation_markers(out["summary"]).split())
    return out


def structure_result(output):
    draft = output["summary"]
    cited = set(cited_numbers_in_order(draft))
    available = {s["index"] for s in output["sources"]}
    problems = []
    if not output["written"] or not draft.strip():
        problems.append("No section was written.")
        problems.extend(output.get("editorial_issues", []))
    if not cited or cited - available or unresolved_numbers(draft):
        problems.append(
            "The section needs citations that resolve to returned passages."
        )
    opening = re.split(r"\n\s*\n", draft.strip(), maxsplit=1)[0]
    if draft.strip() and not cited_numbers_in_order(opening):
        problems.append("The opening paragraph needs a citation.")
    if re.search(r"(?m)^\s*(?:[-+*]\s+|\d+[.)]\s+)", draft):
        problems.append("Write the section in paragraphs instead of a list.")
    if re.search(r"(?m)^\s*(?:#{1,6}\s+|\*\*[^*]+\*\*\s*$)", draft):
        problems.append("The section contains an extra heading.")
    return {
        "type": "brief_structure",
        "passed": not problems,
        "score": float(not problems),
        "message": " ".join(problems)
        or f"{output['words']} words. Cited passages: {len(cited)}. No extra headings.",
    }


class BriefVerdict(BaseModel):
    reason: str = Field(min_length=1)
    unmet: list[str]
    score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_score(self):
        if self.unmet and self.score == 1:
            raise ValueError("Unmet requirements cannot receive full credit.")
        return self


class IntroductionVerdict(BaseModel):
    reason: str = Field(min_length=1)
    unmet: list[str]

    @property
    def score(self) -> float:
        return float(not self.unmet)


class RepeatedFinding(BaseModel):
    new_clause: str = Field(min_length=1)
    existing_clause: str = Field(min_length=1)
    other_heading: str = Field(min_length=1)


class OverlapVerdict(BaseModel):
    reason: str = Field(min_length=1)
    repeats: list[RepeatedFinding]

    @model_validator(mode="after")
    def verify_quotes(self, info: ValidationInfo):
        document = info.context
        for match in self.repeats:
            if match.new_clause not in document["summary"] or not any(
                match.other_heading == s["title"]
                and match.existing_clause in (s.get("content") or "")
                for s in document["siblings"]
            ):
                raise ValueError(
                    "Quote verbatim from the new draft and the named other section."
                )
        if self.repeats:
            pairs = [
                f"“{pair.new_clause}” repeats “{pair.existing_clause}” in {pair.other_heading}."
                for pair in self.repeats
            ]
            self.reason = " ".join([self.reason, *pairs])
        return self

    @property
    def score(self) -> float:
        return float(not self.repeats)


async def _grade(output, prompt, model, system, schema=BriefVerdict):
    from ui.backend.services.test_runner import _judge_call

    for attempt in range(2):
        raw, usage = await _judge_call(prompt, model, system, max_tokens=900)
        output.setdefault("judge_usage", []).append(usage)
        try:
            return schema.model_validate_json(raw, context=output), prompt
        except ValidationError:
            if attempt:
                raise
            template = assistant_prompt_templates.get_template(
                "brief_experiment_judge.j2"
            )
            prompt += "\n" + template.render(repair=True)
    raise RuntimeError("The judge did not return a verdict.")


def _brief_grade_request(template, output, kind, rubric):
    assignment = output["assignment"]
    if kind == "brief_voice":
        return (
            "",
            template.render(voice_system=True),
            template.render(
                profile=assignment["voice_profile"], draft=output["summary"]
            ),
        )
    if kind == "brief_intro_scope":
        if not assignment.get("child_headings"):
            return "Add child headings to evaluate an introduction.", "", ""
        return (
            "",
            template.render(intro_system=True),
            template.render(intro=True, assignment=assignment, draft=output["summary"]),
        )
    overlap = kind == "brief_overlap"
    if overlap and not any(
        (s.get("content") or "").strip() for s in output["siblings"]
    ):
        return "Provide another section with written text to test repetition.", "", ""
    writing = kind == "brief_writing"
    return (
        "",
        template.render(system=True, writing=writing, overlap=overlap),
        template.render(
            rubric=rubric,
            assignment=assignment,
            paragraphs=re.split(r"\n\s*\n", output["summary"].strip()),
            words=len(strip_citation_markers(output["summary"]).split()),
            siblings=output["siblings"],
            sources=[
                {
                    key: source[key]
                    for key in ("index", "title", "page", "headings", "text")
                    if key in source
                }
                for source in output["sources"]
            ],
            standard=output["reference_standard"],
            overlap_only=overlap,
            writing_only=writing,
        ),
    )


async def judge_brief(output, assertions, model):
    template = assistant_prompt_templates.get_template("brief_experiment_judge.j2")
    decisions = {}
    schemas = {
        "brief_intro_scope": IntroductionVerdict,
        "brief_overlap": OverlapVerdict,
        "brief_writing": BriefVerdict,
        "brief_voice": BriefVerdict,
        "llm_judge": BriefVerdict,
    }
    for assertion in assertions:
        kind = brief_assertion_type(assertion)
        if kind not in schemas:
            continue
        if kind == "brief_voice" and not output["assignment"].get("voice_profile"):
            continue
        key = (
            judge_rubric_key(assertion)
            if kind in ("llm_judge", "brief_writing")
            else kind
        )
        if key in decisions:
            continue
        if not output["written"]:
            decisions[key] = (0.0, "No section was written.", "")
            continue
        issue, system, prompt = _brief_grade_request(
            template, output, kind, assertion.get("rubric", "")
        )
        if issue:
            decisions[key] = (0.0, issue, "")
            continue
        verdict, prompt = await _grade(
            output,
            prompt,
            model,
            system,
            schemas[kind],
        )
        decisions[key] = (verdict.score, verdict.reason, system + "\n\n" + prompt)
    return lambda _draft, rubric: decisions[rubric]
