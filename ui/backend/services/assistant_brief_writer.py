"""Build a Brief section from sentences checked against their own evidence."""

import re
from heapq import nlargest
from itertools import chain

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.schemas import BriefSectionPrompt
from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.assistant_grounding import (
    EvidenceQuote,
    Passage,
    ReviewRequest,
    check_answer_citations,
    render_evidence,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.citation_fidelity import (
    match_key,
    split_sentences,
    strip_citation_markers,
)
from utils.llm_factory import message_text


class BriefFinding(EvidenceQuote):
    paragraph: int = Field(ge=1, le=6)
    text: str = Field(min_length=1, max_length=550)


class BriefEvidenceLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: str = Field(min_length=1, max_length=550)


_BRIEF_LINE = TypeAdapter(BriefFinding | BriefEvidenceLimit)
_DEPENDENT_LEAD = re.compile(
    r"^(?:For example|For instance|Similarly|Likewise),\s*", re.I
)
_TRAILING_REFERENCE = re.compile(r"\s+\((\d+(?:,\s*\d+)*)\)$")
_FINDING_WORD = re.compile(r"\b\w{3,}\b")
_DRAFT_FORMAT_ISSUE = (
    "Return only one valid JSON object per line, with no prose outside it. "
    "Each finding needs paragraph, text, citation and quote fields."
)
_FINDING_LENGTH_ISSUE = (
    "A finding's text exceeded 550 characters. Put each supported sentence "
    "in its own record, with the citation and exact quote for that sentence."
)


def _prepare_finding(
    finding: BriefFinding, excerpts: dict[int, str]
) -> tuple[str, str, str] | None:
    text = finding.text.strip().rstrip(".").strip()
    if set(cited_numbers_in_order(text)) - {finding.citation}:
        return None
    text = strip_citation_markers(text).rstrip(".").strip()
    if match := _TRAILING_REFERENCE.search(text):
        labels = {int(number) for number in match[1].split(",")}
        quoted_numbers = set(re.findall(r"\b\d+\b", finding.quote))
        if (
            finding.citation in labels
            and labels <= excerpts.keys()
            and not all(str(label) in quoted_numbers for label in labels)
        ):
            text = text[: match.start()]
    if lead := _DEPENDENT_LEAD.match(text):
        text = text[lead.end() :]
        text = text[:1].upper() + text[1:]
    key = match_key(text)
    quote = match_key(finding.quote)
    if (
        not key
        or len(split_sentences(text)) != 1
        or text.startswith(("#", "-", "*"))
        or "[" in text
        or len(quote.split()) < 2
        or f" {quote} " not in excerpts.get(finding.citation, "")
    ):
        return None
    return f"{text} [{finding.citation}].", key, finding.quote


def _read_draft_lines(raw: str) -> tuple[dict[int, list[BriefFinding]], str, list[str]]:
    paragraphs: dict[int, list[BriefFinding]] = {}
    limit = ""
    issues = []
    for line in raw.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            part = _BRIEF_LINE.validate_json(line)
        except ValidationError as error:
            if any(
                item["loc"][-1:] == ("text",) and item["type"] == "string_too_long"
                for item in error.errors(include_input=False)
            ):
                issues.append(_FINDING_LENGTH_ISSUE)
            else:
                issues.append(_DRAFT_FORMAT_ISSUE)
            continue
        if isinstance(part, BriefFinding):
            paragraphs.setdefault(part.paragraph, []).append(part)
        else:
            limit = part.limit.strip()
    if raw.strip() and not (paragraphs or limit or issues):
        issues.append(_DRAFT_FORMAT_ISSUE)
    return paragraphs, limit, issues


def _brief_draft_text(
    draft: str, evidence: dict[int, Passage], other_claims: set[str]
) -> tuple[str, list[str], dict[str, str]]:
    candidates, limit, issues = _read_draft_lines(draft)
    paragraphs = []
    seen: set[str] = set()
    prepared_quotes = {}
    excerpts = {
        index: f" {match_key(passage_for_agent(passage['text']))} "
        for index, passage in evidence.items()
    }
    for index in sorted(candidates):
        sentences = []
        for candidate in candidates[index][:4]:
            prepared = _prepare_finding(candidate, excerpts)
            if not prepared:
                issues.append(
                    "Every finding needs a standalone sentence, a numeric citation, "
                    "and an exact quote from that passage."
                )
                continue
            sentence, key, quote = prepared
            if key in seen:
                continue
            if key in other_claims:
                issues.append(
                    "Choose a finding that is not already written in another section."
                )
                continue
            sentences.append(sentence)
            prepared_quotes[sentence] = quote
            seen.add(key)
        if sentences:
            paragraphs.append(" ".join(sentences))
    if paragraphs and limit and len(split_sentences(limit)) == 1 and "[" not in limit:
        paragraphs.append(limit.rstrip(".") + ".")
    return "\n\n".join(paragraphs), list(dict.fromkeys(issues)), prepared_quotes


def _combine_findings(drafts: list[str], target: int | None) -> tuple[str, int]:
    """Keep findings intact and place the evidence limit after them."""
    paragraphs = []
    limit = ""
    seen: set[str] = set()
    remaining = target or float("inf")
    draft_paragraphs = chain.from_iterable(draft.split("\n\n") for draft in drafts)
    for paragraph in draft_paragraphs:
        sentences = []
        for sentence in split_sentences(paragraph):
            if not cited_numbers_in_order(sentence):
                limit = limit or sentence
                continue
            plain = strip_citation_markers(sentence)
            key = match_key(plain)
            words = len(plain.split())
            if key in seen or (words > remaining and seen):
                continue
            remaining -= words
            seen.add(key)
            sentences.append(sentence)
        if sentences:
            paragraphs.append(" ".join(sentences))
    if paragraphs and limit and len(limit.split()) <= remaining:
        paragraphs.append(limit)
    text = "\n\n".join(paragraphs)
    return text, len(strip_citation_markers(text).split())


def _similar_findings(
    draft: str, existing: list[tuple[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """Give the reviewer relevant existing findings without sending the full brief."""
    indexed = [
        (heading, finding, set(_FINDING_WORD.findall(match_key(finding))))
        for heading, finding in existing
    ]
    matches = {}
    for sentence in split_sentences(draft):
        words = set(_FINDING_WORD.findall(match_key(strip_citation_markers(sentence))))
        scored = (
            (len(words & previous) / len(words | previous), heading, finding)
            for heading, finding, previous in indexed
            if words and previous
        )
        relevant = [
            {"heading": heading, "finding": finding}
            for score, heading, finding in nlargest(2, scored)
            if score >= 0.3
        ]
        if relevant:
            matches[sentence] = relevant
    return matches


async def write_grounded_brief(
    assignment: str,
    search_focus: str,
    writing_guide: str,
    evidence: dict[int, Passage],
    config: RunnableConfig,
    writer: BaseChatModel,
    review: ReviewRequest | None,
    section: BriefSectionPrompt,
    *,
    target_words: int | None = None,
) -> str:
    """Write independently sourced findings and optionally check their support."""
    if not evidence:
        return ""
    template = assistant_prompt_templates.get_template("brief_evidence_draft.j2")
    system = template.render(system=True)
    stream = get_stream_writer()
    passages = render_evidence(list(evidence.values()))
    existing = [
        (heading.title, strip_citation_markers(sentence))
        for index, heading in enumerate(section.outline)
        if index != section.current
        for sentence in split_sentences(heading.content or "")
        if cited_numbers_in_order(sentence)
    ]
    other_claims = {match_key(finding) for _, finding in existing}
    issues: list[str] = []
    drafts: list[str] = []
    accepted = ""
    written_words = 0
    minimum_words = target_words * 0.85 if target_words else 1
    for _ in range(2):
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=template.render(
                    assignment=assignment,
                    writing_guide=writing_guide,
                    evidence=passages,
                    issues=issues,
                    accepted=accepted,
                    target_words=target_words,
                    written_words=written_words,
                )
            ),
        ]
        reply = await writer.ainvoke(messages, config=config)
        text, issues, prepared_quotes = _brief_draft_text(
            message_text(reply), evidence, other_claims
        )
        if text and review is not None:
            stream({"type": "phase", "phase": "checking_citations"})
            similar = await run_in_threadpool(_similar_findings, text, existing)
            checked = await check_answer_citations(
                text,
                assignment,
                search_focus,
                evidence,
                config,
                review,
                brief_section=True,
                prepared_quotes=prepared_quotes,
                similar_findings=similar,
            )
            text = checked.supported_text
            issues.extend(checked.issues)
        if text:
            drafts.append(text)
            accepted, written_words = _combine_findings(drafts, target_words)
            if written_words >= minimum_words:
                break
        if not issues:
            issues.append(
                "Use relevant documented implementation or measurement and report the limits."
            )
    return accepted
