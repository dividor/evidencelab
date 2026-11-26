"""Check each drafted sentence against the sources it actually cites."""

import asyncio
import re
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, TypeVar

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter

from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.assistant_source_attribution import source_attribution_issues
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.citation_fidelity import match_key, split_sentences
from utils.llm_factory import message_text


def _citation_label(value: object) -> object:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, str) and (match := re.fullmatch(r"\[(\d+)\]", value.strip())):
        return int(match[1])
    return value


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation: Annotated[int, BeforeValidator(_citation_label)]
    quote: str


class SentenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1)
    status: Literal["supported", "non_factual", "evidence_gap", "unsupported"]
    quotes: list[EvidenceQuote] = Field(default_factory=list)
    issue: str = ""


class CitationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[SentenceCheck]
    scope_issues: list[str]


class BriefProseCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[str]


CITATION_CHECK: TypeAdapter[CitationCheck] = TypeAdapter(CitationCheck)
BRIEF_PROSE_CHECK: TypeAdapter[BriefProseCheck] = TypeAdapter(BriefProseCheck)
Passage = dict[str, Any]
_Check = TypeVar("_Check")
_HEADING = re.compile(r"^(#{1,6})[ \t]+\S")
_CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
_SENTENCES_PER_CHECK = 4
_CITATIONS_PER_CHECK = 6
_CONCURRENT_CHECKS = 3


class InvalidAssistantResponse(ValueError):
    """The model returned an invalid response after a format correction."""


class ReviewRequest(Protocol):
    def __call__(
        self,
        system: str,
        prompt: str,
        history: list[BaseMessage],
        config: RunnableConfig,
        schema: TypeAdapter[_Check],
        /,
    ) -> Awaitable[_Check]: ...


@dataclass(frozen=True)
class CitationReview:
    issues: list[str]
    supported_text: str = ""
    revision_base: str = ""

    def revision(
        self,
        *,
        brief_section: bool,
        corrected: bool,
        can_repair_verified_prose: bool,
        has_verified_draft: bool,
    ) -> bool:
        if not self.issues:
            return False
        if not corrected:
            return brief_section or not self.supported_text
        return (
            brief_section
            and not self.supported_text
            and bool(self.revision_base)
            and can_repair_verified_prose
            and not has_verified_draft
        )


async def check_research_draft(
    answer: str,
    question: str,
    search_focus: str,
    evidence: dict[int, Passage],
    config: RunnableConfig,
    request_json: ReviewRequest,
    *,
    brief_section: bool,
    check_citations: bool,
    citation_request: ReviewRequest,
) -> CitationReview:
    review = (
        await check_answer_citations(
            answer,
            question,
            search_focus,
            evidence,
            config,
            citation_request,
            brief_section=brief_section,
        )
        if check_citations
        else CitationReview([])
    )
    readable_draft = review.supported_text if review.issues else answer
    if brief_section and readable_draft:
        template = assistant_prompt_templates.get_template("brief_prose_check.j2")
        review_prose = citation_request if check_citations else request_json
        prose: BriefProseCheck = await review_prose(
            template.render(system=True),
            template.render(assignment=question, draft=readable_draft),
            [],
            config,
            BRIEF_PROSE_CHECK,
        )
        opening = split_sentences(readable_draft.strip())
        issues = prose.issues.copy()
        if not opening or not cited_numbers_in_order(opening[0]):
            issues.append(
                "The opening sentence needs a finding supported by a citation "
                "from the retrieved evidence."
            )
        if issues:
            return CitationReview(issues + review.issues, revision_base=readable_draft)
    return review


def render_evidence(passages: list[Passage]) -> str:
    rows = []
    for passage in passages:
        content = passage_for_agent(passage["text"])
        if len(content) > 2400:
            content = content[:1800] + "\n[excerpt continues]\n" + content[-600:]
        rows.append(f'[{passage["global_index"]}] {passage["title"]}\n{content}')
    return "\n\n".join(rows)


def render_evidence_streams(findings: Iterable[Mapping[str, Any]]) -> str:
    rows = []
    for finding in findings:
        if not finding["topic"]:
            continue
        labels = ", ".join(str(p["global_index"]) for p in finding["evidence"])
        rows.append(f'- {finding["topic"]}: {labels or "no evidence found"}')
    if not rows:
        return ""
    return "Research streams and their evidence labels:\n" + "\n".join(rows) + "\n\n"


def prior_evidence_passages(
    sources: list[Passage], messages: list[BaseMessage], limit: int
) -> list[Passage]:
    """Bring forward sources cited in recent assistant messages."""
    cited = {
        int(number)
        for msg in messages
        if isinstance(msg, AIMessage)
        for group in _CITATION.findall(message_text(msg))
        for number in re.findall(r"\d+", group)
    }
    return [
        {
            "global_index": s["index"],
            "doc_id": s.get("docId"),
            "title": s["title"],
            "page": s.get("page"),
            "text": s["text"],
        }
        for s in sources
        if s.get("index") in cited and s.get("text")
    ][-limit:]


def invalid_citations(answer: str, evidence: list[Passage]) -> list[str]:
    allowed = {p["global_index"] for p in evidence}
    return [
        group
        for group in _CITATION.findall(answer)
        if "-" in group
        or "–" in group
        or any(int(n) not in allowed for n in group.split(","))
    ]


async def check_answer_citations(
    answer: str,
    question: str,
    search_focus: str,
    evidence: dict[int, Passage],
    config: RunnableConfig,
    request_json: ReviewRequest,
    *,
    brief_section: bool,
    prepared_quotes: dict[str, str] | None = None,
    similar_findings: dict[str, list[dict[str, str]]] | None = None,
) -> CitationReview:
    sentences = numbered_sentences(answer)
    for row in sentences:
        if prepared_quotes and (quote := prepared_quotes.get(row["text"])):
            row["prepared_quote"] = quote
        if similar_findings and (matches := similar_findings.get(row["text"])):
            row["similar_findings"] = matches
    mismatches = source_attribution_issues(sentences, evidence)
    system = assistant_prompt_templates.get_template(
        "assistant_grounding_check.j2"
    ).render(brief_section=brief_section, prepared_quotes=bool(prepared_quotes))
    template = assistant_prompt_templates.get_template("assistant_research_request.j2")
    concurrency = asyncio.Semaphore(_CONCURRENT_CHECKS)

    async def check_group(group: list[dict]) -> tuple[list[str], set[int]]:
        labels = dict.fromkeys(index for row in group for index in row["citations"])
        cited = {index: evidence[index] for index in labels}
        request = template.render(
            stage="verify",
            question=question,
            search_focus=search_focus,
            sentences=group,
            evidence=render_evidence(list(cited.values())),
        )
        async with concurrency:
            try:
                verdict: CitationCheck = await request_json(
                    system, request, [], config, CITATION_CHECK
                )
            except InvalidAssistantResponse:
                if not prepared_quotes:
                    raise
                return ["The checker could not verify this group of findings."], set()
        return citation_issues(
            group,
            {
                index: passage_for_agent(passage["text"])
                for index, passage in cited.items()
            },
            verdict,
            keep_evidence_notes=brief_section,
        )

    results = await asyncio.gather(
        *(check_group(group) for group in citation_check_batches(sentences))
    )
    issues = [issue for group_issues, _ in results for issue in group_issues]
    supported = set().union(*(accepted for _, accepted in results))
    issues += [message for index, message in mismatches.items() if index in supported]
    supported.difference_update(mismatches)
    if not any(row["citations"] and row["id"] in supported for row in sentences):
        supported.clear()
    return CitationReview(
        issues, retain_supported_sentences(answer, sentences, supported)
    )


def citation_check_batches(sentences: list[dict]) -> Iterable[list[dict]]:
    """Bound the number of verdicts and source quotes requested in each reply."""
    batch: list[dict] = []
    citation_count = 0
    for sentence in sentences:
        size = len(sentence["citations"])
        if batch and (
            len(batch) >= _SENTENCES_PER_CHECK
            or citation_count + size > _CITATIONS_PER_CHECK
        ):
            yield batch
            batch = []
            citation_count = 0
        batch.append(sentence)
        citation_count += size
    if batch:
        yield batch


def numbered_sentences(answer: str) -> list[dict]:
    return [
        {"id": index, "text": sentence, "citations": cited_numbers_in_order(sentence)}
        for index, sentence in enumerate(split_sentences(answer), start=1)
    ]


def _heading_stack(
    headings: list[tuple[int, str]], depth: int, approved: bool, sentence: str
) -> list[tuple[int, str]]:
    retained = [item for item in headings if item[0] < depth]
    if approved:
        retained.append((depth, sentence))
    return retained


def retain_supported_sentences(
    answer: str, sentences: list[dict], supported: set[int]
) -> str:
    parts: list[str] = []
    headings: list[tuple[int, str]] = []
    offset = 0
    newline = ""
    for row in sentences:
        sentence = row["text"]
        start = answer.index(sentence, offset)
        between = answer[offset:start]
        if "\n" in between:
            newline = "\n\n" if "\n\n" in between else newline or "\n"
        offset = start + len(sentence)
        approved = row["id"] in supported
        if match := _HEADING.match(sentence):
            headings = _heading_stack(headings, len(match[1]), approved, sentence)
            continue
        if not approved:
            continue
        if parts:
            parts.append("\n\n" if headings else newline or " ")
        if headings:
            parts.append("\n\n".join(heading for _, heading in headings) + "\n\n")
            headings.clear()
        parts.append(sentence)
        newline = ""
    return "".join(parts)


def _missing_quotes(
    check: SentenceCheck,
    cited: set[int],
    excerpts: dict[int, str],
    prepared_quote: str = "",
) -> set[int]:
    substantiated = set()
    quotes = check.quotes.copy()
    if prepared_quote and len(cited) == 1:
        quotes.append(EvidenceQuote(citation=next(iter(cited)), quote=prepared_quote))
    for source in quotes:
        needle = match_key(source.quote)
        if source.citation in cited and len(needle.split()) >= 2:
            if f" {needle} " in excerpts.get(source.citation, ""):
                substantiated.add(source.citation)
    return cited - substantiated


def citation_issues(
    sentences: list[dict],
    evidence: dict[int, str],
    verdict: CitationCheck,
    *,
    keep_evidence_notes: bool = False,
) -> tuple[list[str], set[int]]:
    checks = {row.id: row for row in verdict.sentences}
    expected = {row["id"] for row in sentences}
    if len(verdict.sentences) != len(expected) or set(checks) != expected:
        return [
            "The citation checker did not assess each sentence exactly once."
        ], set()

    excerpts = {index: f" {match_key(text)} " for index, text in evidence.items()}
    issues = list(verdict.scope_issues)
    supported = set()
    notes = set()
    for row in sentences:
        check = checks[row["id"]]
        cited = set(row["citations"])
        if check.status == "evidence_gap" and not cited:
            notes.add(check.id)
            continue
        if check.status == "non_factual" and not cited and not keep_evidence_notes:
            if _HEADING.match(row["text"]):
                notes.add(check.id)
            continue
        if check.status != "supported" or not cited:
            issues.append(
                f"Sentence {check.id}: {check.issue or 'Factual content lacks citation support.'}"
            )
            continue
        if missing := _missing_quotes(
            check, cited, excerpts, row.get("prepared_quote", "")
        ):
            labels = ", ".join(f"[{index}]" for index in sorted(missing))
            issues.append(f"Sentence {check.id} lacks verified quotes from {labels}.")
        else:
            supported.add(check.id)
    if verdict.scope_issues:
        return issues, set()
    return issues, supported | notes
