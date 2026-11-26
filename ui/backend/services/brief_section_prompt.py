"""The deep-research prompt for one Brief section.

The Brief researches each section with one deep-research assistant turn. Its
prompt weaves in the brief topic, the section's place in the outline, the
author's guidance and voice, and, for an Update, the current draft. The
browser sends those parts separately (``BriefSectionPrompt``), each within
the limit it has when stored, and the prompt is written here.
"""

import re
from textwrap import shorten
from typing import List, Optional

from fastapi import HTTPException

from ui.backend.auth.schemas import (
    BriefOutlineSection,
    BriefSectionPrompt,
    BriefSurveyPrompt,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.group_settings import BRIEF_SECTION_PROMPT_KEY

# Characters of a written section quoted in the outline as what it covers.
_GIST_CHARS = 180
_SEARCH_QUERY_CHARS = 350
_BRIEF_PROMPT_MAX_LENGTH = 12000

_FINAL_ANSWER_RULE = (
    "Your final answer must be the finished section text itself — never a "
    "description of what you are about to do, a promise to research, or "
    "narration of your process."
)


def brief_section_prompt_default() -> str:
    """The editable writing instructions shown in Group Settings → Brief."""
    return (
        assistant_prompt_templates.get_template("brief_section_instructions.j2")
        .render()
        .strip()
    )


def validate_brief_section_prompt(settings: dict) -> None:
    """Normalize an override in the same settings record as the section length."""
    if BRIEF_SECTION_PROMPT_KEY not in settings:
        return
    prompt = settings[BRIEF_SECTION_PROMPT_KEY]
    if not isinstance(prompt, str) or len(prompt.strip()) > _BRIEF_PROMPT_MAX_LENGTH:
        raise HTTPException(
            status_code=422, detail="Enter a Brief prompt of up to 12,000 characters."
        )
    if prompt.strip():
        settings[BRIEF_SECTION_PROMPT_KEY] = prompt.strip()
    else:
        del settings[BRIEF_SECTION_PROMPT_KEY]


def brief_section_prompt_for_groups(groups) -> str | None:
    """Read the first Brief override in the existing group order."""
    return next(
        (
            prompt
            for group in groups
            if (prompt := (group.search_settings or {}).get(BRIEF_SECTION_PROMPT_KEY))
        ),
        None,
    )


def _gist(markdown: str, max_chars: int = _GIST_CHARS) -> str:
    """The start of a section's markdown as plain text, without citation
    markers, so the model knows what it covers without spending tokens."""
    text = re.sub(r"```[\s\S]*?```", " ", markdown)
    text = re.sub(r"\[(\d+)\]", "", text)
    text = re.sub(r"[#*_>`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return f"{text[:max_chars]}…" if len(text) > max_chars else text


def _parent_title(outline: List[BriefOutlineSection], current: int) -> str:
    """For a sub-section, the nearest heading above it; otherwise ''."""
    if outline[current].level != 2:
        return ""
    for section in reversed(outline[:current]):
        if section.level == 1:
            return section.title.strip()
    return ""


def brief_search_query(brief: BriefSectionPrompt | BriefSurveyPrompt) -> str:
    """Use the topic and headings for retrieval, leaving writing instructions in the prompt."""
    parts: tuple[str | None, ...]
    if isinstance(brief, BriefSectionPrompt):
        parts = (
            brief.outline[brief.current].title,
            _parent_title(brief.outline, brief.current),
            brief.topic,
        )
    else:
        parts = (brief.topic,)
    terms = dict.fromkeys(
        " ".join(part.split()) for part in parts if part and part.strip()
    )
    query = " ".join(terms)
    return (
        shorten(query, width=_SEARCH_QUERY_CHARS, placeholder="")
        or query[:_SEARCH_QUERY_CHARS]
    )


def _sub_section_titles(outline: List[BriefOutlineSection], current: int) -> List[str]:
    """The sub-headings directly under a top-level heading."""
    titles: List[str] = []
    for section in outline[current + 1 :]:
        if section.level != 2:
            break
        titles.append(section.title)
    return titles


def outline_context(outline: List[BriefOutlineSection], current: int) -> str:
    """The brief's outline, with the section being written marked and a gist
    of each written section, plus scope rules so the section does not repeat
    material that belongs elsewhere. '' for a brief with one section."""
    if len(outline) <= 1:
        return ""
    lines = []
    for i, section in enumerate(outline):
        indent = "  - " if section.level == 2 else "- "
        marker = " ← the section you are writing" if i == current else ""
        gist = ""
        if i != current and section.content:
            gist = f" (already written; covers: {_gist(section.content)})"
        lines.append(f"{indent}{section.title}{marker}{gist}")
    parts = [
        "For context, the full outline of the brief is:\n" + "\n".join(lines),
        "Keep this section strictly to its own scope: do NOT repeat or pre-empt "
        "material that belongs in the other sections listed above.",
    ]
    # A top-level heading with sub-headings introduces them; the detail
    # belongs to the sub-sections that follow it.
    if outline[current].level != 2:
        subs = _sub_section_titles(outline, current)
        if subs:
            parts.append(
                f"This section has sub-sections ({'; '.join(subs)}) — write it as "
                "a short high-level introduction to the theme and leave the "
                "detail to those sub-sections."
            )
    return " ".join(parts)


def _update_instruction(instruction: str, published_after: Optional[str]) -> str:
    after = (published_after or "")[:10]
    if after:
        base = (
            "Search the document library for relevant sources PUBLISHED AFTER "
            f"{after} and fold any new findings into the draft, citing them. "
            "Keep the existing content; add or refresh only where newer evidence "
            "warrants. If no newer sources are found, return the draft unchanged "
            "and note that no newer sources were available."
        )
    else:
        base = (
            "Search the document library for the most recent relevant sources "
            "and fold any new findings into the draft, citing them."
        )
    return f"{base} Additional instruction: {instruction}" if instruction else base


def _revise_prompt(
    scope: str,
    draft: str,
    instruction: str,
    guidance: str,
    published_after: Optional[str],
) -> str:
    """Update: keep the draft and fold in newer sources, returning the full
    section with one sequential set of citation markers."""
    parts = [
        f"You are revising {scope}.",
        "Here is the current draft of the section. Preserve its wording, "
        "structure and citations except where the instruction below requires "
        f'a change:\n\n"""\n{draft}\n"""',
        _update_instruction(instruction, published_after),
        "Return the FULL revised section as markdown with sequential [n] "
        "citation markers and cite a source for every claim.",
    ]
    if guidance:
        parts.append(f"Overall brief guidance: {guidance}")
    return " ".join(parts)


def _generate_prompt(scope: str, parent: str, guidance: str, focus: str) -> str:
    parts = [f"Write {scope}."]
    if parent:
        parts.append(
            f'This section sits under the parent section "{parent}" — keep it '
            "specifically about that aspect of the brief and avoid repeating "
            "material that belongs in sibling sections."
        )
    parts.append(
        "Search the document library for evidence relevant to this specific "
        "section and cite a source for every claim."
    )
    parts.append(_FINAL_ANSWER_RULE)
    if guidance:
        parts.append(f"Overall brief guidance: {guidance}")
    if focus:
        parts.append(f"Focus for this section: {focus}")
    return " ".join(parts)


def build_section_prompt(section: BriefSectionPrompt) -> str:
    """The deep-research prompt for the section at ``section.current``."""
    heading = section.outline[section.current].title
    topic = (section.topic or "").strip()
    guidance = (section.instructions or "").strip()
    draft = (section.draft or "").strip()
    voice = (section.voice_instructions or "").strip()
    scope = (
        f'the "{heading}" section of an evidence brief on "{topic}"'
        if topic
        else f'the "{heading}" section of an evidence brief'
    )
    if section.mode == "update" and draft:
        prompt = _revise_prompt(
            scope,
            draft,
            (section.instruction or "").strip(),
            guidance,
            section.published_after,
        )
    else:
        prompt = _generate_prompt(
            scope,
            _parent_title(section.outline, section.current),
            guidance,
            (section.focus or "").strip(),
        )
    outline = outline_context(section.outline, section.current)
    if outline:
        prompt = f"{prompt} {outline}"
    if voice:
        prompt = (
            f"{prompt} Voice & tone profile — write the section in this style: {voice}"
        )
    return prompt


def build_survey_prompt(survey: BriefSurveyPrompt) -> str:
    """The research prompt that surveys the library before an outline is drafted."""
    base = (
        "Research the document library to inform an evidence brief on "
        f'"{survey.topic}".'
    )
    instructions = (survey.instructions or "").strip()
    if not instructions:
        return base
    return (
        f"{base} Follow these author instructions closely and let them drive what "
        "you search for — focus your queries on the specific angles, sectors, "
        "regions, populations and outcomes the instructions call for, not just "
        f"generic restatements of the topic: {instructions}"
    )
