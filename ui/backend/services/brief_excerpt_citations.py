"""Recover omitted excerpt references before a Brief draft is checked."""

import re

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    ReviewRequest,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.citation_fidelity import split_sentences


class ExcerptMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentence: int
    excerpts: list[int]


class ExcerptMatches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matches: list[ExcerptMatch]


_MATCHES: TypeAdapter[ExcerptMatches] = TypeAdapter(ExcerptMatches)


_NUMERIC_MARKER = re.compile(r"\[([0-9, \t–—-]+)\]")
_EXCERPT_INTERVAL = re.compile(r"([0-9]+)\s*[-–—]\s*([0-9]+)")


def expand_excerpt_ranges(draft: str, labels: set[int]) -> str:
    """Expand only ranges made entirely of labels in this writer's evidence."""
    known = {str(label): label for label in labels}

    def expand(marker: re.Match) -> str:
        body = marker[1]
        if not any(dash in body for dash in "-–—"):
            return marker[0]
        numbers = []
        for item in body.split(","):
            item = item.strip()
            if item in known:
                numbers.append(known[item])
                continue
            interval = _EXCERPT_INTERVAL.fullmatch(item)
            if not interval or interval[1] not in known or interval[2] not in known:
                return marker[0]
            first, last = known[interval[1]], known[interval[2]]
            if not 0 <= last - first < len(labels):
                return marker[0]
            span = range(first, last + 1)
            if not labels.issuperset(span):
                return marker[0]
            numbers.extend(span)
        return "[" + ", ".join(str(n) for n in dict.fromkeys(numbers)) + "]"

    return _NUMERIC_MARKER.sub(expand, draft)


async def cite_missing_excerpts(
    raw: str,
    passages: str,
    labels: set[int],
    config: RunnableConfig,
    request: ReviewRequest,
) -> str:
    blocks = raw.strip().split("\n\n")
    missing: dict[int, tuple[int, int, str]] = {}
    paragraphs: list[list[str]] = []
    for block in blocks:
        sentences = split_sentences(block)
        for index, sentence in enumerate(sentences):
            if not cited_numbers_in_order(sentence):
                missing[len(missing) + 1] = (len(paragraphs), index, sentence)
        paragraphs.append(sentences)
    if not missing:
        return raw
    matches = await _match_excerpts(raw, passages, labels, missing, config, request)
    for row in matches:
        if row.excerpts:
            paragraph, index, sentence = missing[row.sentence]
            marker = ", ".join(str(label) for label in dict.fromkeys(row.excerpts))
            text = sentence.rstrip(".!?")
            ending = sentence[len(text) :] or "."
            paragraphs[paragraph][index] = f"{text} [{marker}]{ending}"
    return "\n\n".join(" ".join(sentences) for sentences in paragraphs)


async def _match_excerpts(draft, passages, labels, missing, config, request):
    template = assistant_prompt_templates.get_template("brief_excerpt_citations.j2")
    sentences = {key: row[2] for key, row in missing.items()}
    invalid = ""
    for _ in range(2):
        response = await request(
            template.render(system=True),
            template.render(
                draft=draft,
                passages=passages,
                sentences=sentences,
                requested_ids=list(sentences),
                validation_problem=invalid,
            ),
            [],
            config,
            _MATCHES,
        )
        matches = response.matches
        if sorted(row.sentence for row in matches) != list(sentences):
            invalid = "The Brief citation review returned invalid sentence numbers"
        elif any(not labels.issuperset(row.excerpts) for row in matches):
            invalid = "The Brief citation review returned an unknown excerpt"
        else:
            return matches
    raise InvalidAssistantResponse(invalid)
