"""Generate an experimental section through the same research service as Brief."""

import re

from pydantic import BaseModel, Field, ValidationError, model_validator

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
        voice_instructions=case.voice,
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
            voice=case.voice,
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


async def _grade(output, prompt, model, system, schema=BriefVerdict):
    from ui.backend.services.test_runner import _judge_call

    for attempt in range(2):
        raw, usage = await _judge_call(prompt, model, system, max_tokens=900)
        output.setdefault("judge_usage", []).append(usage)
        try:
            return schema.model_validate_json(raw), prompt
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
    return (
        "",
        template.render(system=True),
        template.render(
            rubric=template.render(overlap=True) if overlap else rubric,
            assignment=assignment,
            draft=output["summary"],
            siblings=output["siblings"],
            sources=output["sources"],
            standard=output["reference_standard"],
            overlap_only=overlap,
        ),
    )


async def judge_brief(output, assertions, model):
    template = assistant_prompt_templates.get_template("brief_experiment_judge.j2")
    decisions = {}
    for assertion in assertions:
        kind = assertion["type"]
        if kind not in ("llm_judge", "brief_overlap", "brief_intro_scope"):
            continue
        key = assertion.get("rubric", "") if kind == "llm_judge" else kind
        if key in decisions:
            continue
        if not output["written"]:
            decisions[key] = (0.0, "No section was written.", "")
            continue
        issue, system, prompt = _brief_grade_request(template, output, kind, key)
        if issue:
            decisions[key] = (0.0, issue, "")
            continue
        verdict, prompt = await _grade(
            output,
            prompt,
            model,
            system,
            IntroductionVerdict if kind == "brief_intro_scope" else BriefVerdict,
        )
        decisions[key] = (verdict.score, verdict.reason, system + "\n\n" + prompt)
    return lambda _draft, rubric: decisions[rubric]
