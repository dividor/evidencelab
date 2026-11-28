"""Review the findings of a new section against previously written sections."""

import re
from decimal import Decimal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    ReviewRequest,
    numbered_sentences,
    retain_supported_sentences,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.citation_fidelity import match_key, strip_citation_markers


def _words(text: str) -> str:
    return match_key(strip_citation_markers(text))


def _figures(text: str) -> set[Decimal]:
    """Read figures from the prose, excluding source numbers and grouping commas."""
    prose = strip_citation_markers(text)
    numbers = re.findall(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?", prose)
    return {Decimal(number.replace(",", "")) for number in numbers}


class RepeatedClause(BaseModel):
    new_clause: str = Field(min_length=1)
    # An empty quote supplies no evidence for removing the new clause.
    existing_clause: str
    equivalent_amount: str = ""

    def accounts_for_figures(self) -> bool:
        if _figures(self.new_clause) <= _figures(self.existing_clause):
            return True
        amount = _words(self.equivalent_amount)
        return bool(amount) and f" {amount} " in f" {_words(self.existing_clause)} "


class RepeatedSentence(BaseModel):
    id: int = Field(ge=1)
    pairs: list[RepeatedClause] = Field(min_length=1)

    def covers(self, sentence: str, earlier: list[str]) -> bool:
        quoted = _words(" ".join(pair.new_clause for pair in self.pairs))
        if not quoted or quoted != _words(sentence):
            return False
        for pair in self.pairs:
            if not pair.accounts_for_figures():
                return False
            existing = _words(pair.existing_clause)
            if not existing or not any(
                f" {existing} " in f" {row} " for row in earlier
            ):
                return False
        return True


class BriefRepetitionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duplicates: list[RepeatedSentence]

    def confirmed(self, findings: list[dict], siblings: list[dict]) -> set[int]:
        eligible = {row["id"] for row in (findings if siblings else findings[1:])}
        if any(repeat.id not in eligible for repeat in self.duplicates):
            raise InvalidAssistantResponse(
                "The Brief repetition check returned invalid finding labels"
            )
        proposed = {repeat.id: repeat for repeat in self.duplicates}
        earlier = [_words(row["finding"]) for row in siblings]
        confirmed = set()
        for row in findings:
            repeat = proposed.get(row["id"])
            if repeat and repeat.covers(row["text"], earlier):
                confirmed.add(row["id"])
            else:
                earlier.append(_words(row["text"]))
        return confirmed


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
        return _standalone_opening(text)
    template = assistant_prompt_templates.get_template("brief_repeated_findings.j2")
    duplicates: set[int] = set()
    for batch in _sibling_batches(siblings) if siblings else [[]]:
        result: BriefRepetitionCheck = await request_json(
            template.render(system=True),
            template.render(
                findings=[(row["id"], row["text"]) for row in findings],
                siblings=[row["finding"] for row in batch],
            ),
            [],
            config,
            _BRIEF_REPETITION_CHECK,
        )
        duplicates.update(result.confirmed(findings, batch))
    if all(row["id"] in duplicates for row in findings):
        return ""
    kept = retain_supported_sentences(
        text, sentences, {row["id"] for row in sentences} - duplicates
    )
    return _standalone_opening(kept)


def _standalone_opening(text: str) -> str:
    """A lead-in such as 'Similarly' needs a preceding sentence."""
    return re.sub(
        r"^(?:for example|for instance|similarly|likewise),\s*(\w)",
        lambda match: match[1].upper(),
        text,
        count=1,
        flags=re.I,
    )
