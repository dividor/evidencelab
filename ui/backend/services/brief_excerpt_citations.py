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


_MATCHES: TypeAdapter[list[ExcerptMatch]] = TypeAdapter(list[ExcerptMatch])


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
        sentences = [block] if block.startswith("Limit: ") else split_sentences(block)
        for index, sentence in enumerate(sentences):
            if not block.startswith("Limit: ") and not cited_numbers_in_order(sentence):
                missing[len(missing) + 1] = (len(paragraphs), index, sentence)
        paragraphs.append(sentences)
    if not missing:
        return raw
    template = assistant_prompt_templates.get_template("brief_excerpt_citations.j2")
    matches: list[ExcerptMatch] = await request(
        template.render(system=True),
        template.render(
            draft=raw,
            passages=passages,
            sentences={k: v[2] for k, v in missing.items()},
        ),
        [],
        config,
        _MATCHES,
    )
    if sorted(row.sentence for row in matches) != list(missing):
        raise InvalidAssistantResponse(
            "The Brief citation review returned invalid sentence numbers"
        )
    for row in matches:
        if not labels.issuperset(row.excerpts):
            raise InvalidAssistantResponse(
                "The Brief citation review returned an unknown excerpt"
            )
        if row.excerpts:
            paragraph, index, sentence = missing[row.sentence]
            marker = ", ".join(str(label) for label in dict.fromkeys(row.excerpts))
            text = sentence.rstrip(".!?")
            ending = sentence[len(text) :] or "."
            paragraphs[paragraph][index] = f"{text} [{marker}]{ending}"
    return "\n\n".join(" ".join(sentences) for sentences in paragraphs)
