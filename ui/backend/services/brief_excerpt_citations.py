"""Recover omitted excerpt references before a Brief draft is checked."""

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
