"""Review the findings of a new section against previously written sections."""

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    ReviewRequest,
    numbered_sentences,
    retain_supported_sentences,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates


class BriefRepetitionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duplicates: list[int]


_BRIEF_REPETITION_CHECK = TypeAdapter(BriefRepetitionCheck)


def _sibling_batches(findings: list[tuple[str, str]], budget: int = 12000):
    """Compare all written sections in bounded requests, including long manual edits."""
    batch: list[dict[str, str]] = []
    size = 0
    for title, finding in findings:
        for start in range(0, len(finding), budget):
            part = finding[start : start + budget]
            if batch and size + len(part) + len(title) > budget:
                yield batch
                batch = []
                size = 0
            batch.append({"heading": title, "finding": part})
            size += len(part) + len(title)
    if batch:
        yield batch


async def remove_repeated_brief_findings(
    text: str,
    config: RunnableConfig,
    request_json: ReviewRequest,
    siblings: list[tuple[str, str]] | None = None,
) -> str:
    """Compare accepted findings to one another and to previously written sections."""
    sentences = numbered_sentences(text)
    findings = [
        {"id": row["id"], "text": row["text"]} for row in sentences if row["citations"]
    ]
    if not findings or (len(findings) == 1 and not siblings):
        return text
    template = assistant_prompt_templates.get_template("brief_repeated_findings.j2")
    duplicates: set[int] = set()
    for batch in _sibling_batches(siblings) if siblings else [[]]:
        result: BriefRepetitionCheck = await request_json(
            template.render(system=True),
            template.render(findings=findings, siblings=batch),
            [],
            config,
            _BRIEF_REPETITION_CHECK,
        )
        eligible = {row["id"] for row in (findings if batch else findings[1:])}
        if set(result.duplicates) - eligible:
            raise InvalidAssistantResponse(
                "The Brief repetition check returned invalid finding labels"
            )
        duplicates.update(result.duplicates)
    return retain_supported_sentences(
        text, sentences, {row["id"] for row in sentences} - duplicates
    )
