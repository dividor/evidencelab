"""Build a Brief section from sentences checked against their own evidence."""

import re
from heapq import nlargest
from itertools import chain

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.schemas import BriefSectionPrompt
from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.assistant_grounding import (
    EvidenceQuote,
    InvalidAssistantResponse,
    Passage,
    ReviewRequest,
    check_answer_citations,
    numbered_sentences,
    retain_supported_sentences,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.brief_evidence_selection import select_brief_evidence
from ui.backend.services.brief_repetition import remove_repeated_brief_findings
from ui.backend.services.citation_fidelity import (
    match_key,
    split_sentences,
    strip_citation_markers,
)
from utils.llm_factory import message_text


class BriefFinding(BaseModel):
    text: str = Field(min_length=1)
    sources: list[EvidenceQuote]


class FindingScopeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1)
    subject: str
    reason: str
    source_matches_assignment: bool
    unsupported_phrases: list[str]
    keep: bool
    covers_other_heading: bool
    in_scope_revision: str | None = None


class FindingScopeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviews: list[FindingScopeDecision]


_FINDING_SCOPE = TypeAdapter(FindingScopeReview)
_TRAILING_REFERENCE = re.compile(r"\s+\((\d+(?:,\s*\d+)*)\)$")
_FINDING_WORD = re.compile(r"\b\w{3,}\b")
_DRAFT_FORMAT_ISSUE = "Cite a numbered excerpt before the end of each factual sentence."


def _prepare_finding(
    finding: BriefFinding, excerpts: dict[int, str]
) -> tuple[str, str, list[EvidenceQuote]] | None:
    text = finding.text.strip().rstrip(".").strip()
    citations = list(dict.fromkeys(src.citation for src in finding.sources))
    if match := _TRAILING_REFERENCE.search(text):
        labels = {int(number) for number in match[1].split(",")}
        quoted_numbers = set(
            re.findall(r"\b\d+\b", " ".join(src.quote for src in finding.sources))
        )
        if (
            labels.intersection(citations)
            and labels <= excerpts.keys()
            and not all(str(label) in quoted_numbers for label in labels)
        ):
            text = text[: match.start()]
    key = match_key(text)
    for src in finding.sources:
        quote = match_key(src.quote)
        if len(quote.split()) < 2 or f" {quote} " not in excerpts.get(src.citation, ""):
            return None
    if (
        not key
        or len(split_sentences(text)) != 1
        or text.startswith(("#", "-", "*"))
        or "[" in text
    ):
        return None
    markers = ", ".join(str(label) for label in citations)
    return f"{text} [{markers}].", key, finding.sources


def _read_draft_lines(raw: str, quotes: dict[int, tuple[int, str]]):
    paragraphs = []
    issues = []
    limit = ""
    for block in re.split(r"\n\s*\n", raw.strip()):
        if block.startswith("Limit: "):
            limit = block.splitlines()[0].removeprefix("Limit: ").strip()
            if len(block.splitlines()) > 1:
                issues.append(_DRAFT_FORMAT_ISSUE)
            continue
        findings = []
        for sentence in split_sentences(block):
            labels = cited_numbers_in_order(sentence)
            if not labels or any(label not in quotes for label in labels):
                issues.append(_DRAFT_FORMAT_ISSUE)
                continue
            text = strip_citation_markers(sentence)
            if text.strip(".!? "):
                findings.append(
                    BriefFinding(
                        text=text,
                        sources=[
                            EvidenceQuote(
                                citation=quotes[label][0], quote=quotes[label][1]
                            )
                            for label in labels
                        ],
                    )
                )
        paragraphs.append(findings)
    return paragraphs, limit, issues


def _brief_draft_text(
    draft: str,
    evidence: dict[int, Passage],
    other_claims: set[str],
    quotes: dict[int, tuple[int, str]],
) -> tuple[str, list[str], dict[str, list[EvidenceQuote]]]:
    candidates, limit, issues = _read_draft_lines(draft, quotes)
    paragraphs = []
    seen: set[str] = set()
    prepared_quotes = {}
    excerpts = {
        index: f" {match_key(passage_for_agent(passage['text']))} "
        for index, passage in evidence.items()
    }
    for paragraph in candidates:
        sentences = []
        for candidate in paragraph:
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


async def _review_finding_scope(
    draft: str,
    section: BriefSectionPrompt,
    evidence: dict[int, Passage],
    prepared_quotes: dict[str, list[EvidenceQuote]],
    similar: dict[str, list[dict[str, str]]],
    subject: str,
    config: RunnableConfig,
    review: ReviewRequest,
) -> tuple[str, list[str]]:
    sentences = numbered_sentences(draft)
    template = assistant_prompt_templates.get_template("brief_finding_scope.j2")
    request = template.render(
        heading=section.outline[section.current].title,
        topic=section.topic,
        subject=subject,
        guidance=section.focus,
        instructions=section.instructions,
        voice=section.voice_instructions,
        other_headings=[
            s.title for i, s in enumerate(section.outline) if i != section.current
        ],
        sentences=[
            _finding_for_scope(row, evidence, prepared_quotes, similar)
            for row in sentences
        ],
    )
    decision: FindingScopeReview = await review(
        template.render(system=True), request, [], config, _FINDING_SCOPE
    )
    if sorted(row.id for row in decision.reviews) != [row["id"] for row in sentences]:
        raise InvalidAssistantResponse("The scope check must assess each finding once")
    return _apply_scope_review(draft, sentences, decision, prepared_quotes)


def _finding_for_scope(
    row: dict,
    evidence: dict[int, Passage],
    prepared_quotes: dict[str, list[EvidenceQuote]],
    similar: dict[str, list[dict[str, str]]],
) -> dict:
    text = row["text"]
    return {
        "id": row["id"],
        "text": text,
        "supporting_quotes": [s.model_dump() for s in prepared_quotes.get(text, [])],
        "similar": similar.get(text, []),
        "sources": [
            {
                "title": evidence[label]["title"],
                "subject_quote": evidence[label]["brief_subject_evidence"],
            }
            for label in row["citations"]
        ],
    }


def _apply_scope_review(
    draft: str,
    sentences: list[dict],
    decision: FindingScopeReview,
    prepared_quotes: dict[str, list[EvidenceQuote]],
) -> tuple[str, list[str]]:
    approved = set()
    revisions = {}
    issues = []
    for row, review in zip(sentences, sorted(decision.reviews, key=lambda row: row.id)):
        if not review.source_matches_assignment:
            issues.append(
                f"Source does not establish the required subject: {review.reason}"
            )
            continue
        if review.keep and not (
            review.covers_other_heading or review.unsupported_phrases
        ):
            approved.add(row["id"])
            continue
        original = row["text"]
        issues.append(f"Rejected finding: {original} Reason: {review.reason}")
        revision = (review.in_scope_revision or "").strip().rstrip(".")
        if _valid_scope_revision(revision, row, prepared_quotes):
            revised = f"{revision} [{row['citations'][0]}]."
            revisions[original] = revised
            prepared_quotes[revised] = prepared_quotes[original]
            approved.add(row["id"])
    text = retain_supported_sentences(draft, sentences, approved)
    for original, revised in revisions.items():
        text = text.replace(original, revised, 1)
    return text, issues


def _valid_scope_revision(
    revision: str,
    row: dict,
    prepared_quotes: dict[str, list[EvidenceQuote]],
) -> bool:
    return (
        bool(revision)
        and len(revision) <= 550
        and not revision.startswith(("#", "-", "*"))
        and "[" not in revision
        and len(split_sentences(revision)) == 1
        and len(row["citations"]) == 1
        and row["text"] in prepared_quotes
    )


async def _verify_draft_findings(
    draft: str,
    prepared_quotes: dict[str, list[EvidenceQuote]],
    previous_findings: list[tuple[str, str]],
    assignment: str,
    subject: str,
    search_focus: str,
    evidence: dict[int, Passage],
    config: RunnableConfig,
    review: ReviewRequest,
    review_scope: ReviewRequest,
    section: BriefSectionPrompt,
) -> tuple[str, list[str]]:
    similar = await run_in_threadpool(_similar_findings, draft, previous_findings)
    text, issues = await _review_finding_scope(
        draft,
        section,
        evidence,
        prepared_quotes,
        similar,
        subject,
        config,
        review_scope,
    )
    if not text:
        return "", issues
    similar = await run_in_threadpool(_similar_findings, text, previous_findings)
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
    if checked.issues:
        supported = set(split_sentences(checked.supported_text))
        issues.extend(checked.issues)
        issues.extend(
            f"Finding removed during evidence check: {finding}"
            for finding in prepared_quotes
            if finding in text and finding not in supported
        )
    return checked.supported_text, issues


def _written_sibling_findings(section: BriefSectionPrompt) -> list[tuple[str, str]]:
    return [
        (heading.title, strip_citation_markers(sentence))
        for index, heading in enumerate(section.outline)
        if index != section.current
        for sentence in split_sentences(heading.content or "")
    ]


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
    review_scope: ReviewRequest,
    target_words: int | None = None,
    earlier_text: str = "",
) -> str:
    """Write independently sourced findings and optionally check their support."""
    if not evidence:
        return earlier_text
    evidence, (passages, quotes), subject = await select_brief_evidence(
        assignment, evidence, config, review_scope, target_words
    )
    if not evidence:
        return earlier_text
    template = assistant_prompt_templates.get_template("brief_evidence_draft.j2")
    system = template.render(system=True)
    stream = get_stream_writer()
    existing = _written_sibling_findings(section)
    sibling_matches = (
        await run_in_threadpool(_similar_findings, passages, existing)
        if existing
        else {}
    )
    other_claims = {match_key(finding) for _, finding in existing}
    current = section.outline[section.current].title
    issues: list[str] = []
    # Once new evidence is accepted it can supersede the earlier evidence-gap note.
    drafts = [p for p in earlier_text.split("\n\n") if cited_numbers_in_order(p)]
    accepted = earlier_text
    written_words = len(strip_citation_markers(accepted).split())
    minimum_words = target_words * 0.85 if target_words else 1
    for _ in range(2):
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=template.render(
                    assignment=assignment,
                    subject=subject,
                    writing_guide=writing_guide,
                    voice=section.voice_instructions,
                    evidence=passages,
                    issues=issues,
                    accepted=strip_citation_markers(accepted),
                    target_words=target_words,
                    written_words=written_words,
                    sibling_matches=sibling_matches,
                )
            ),
        ]
        reply = await writer.ainvoke(messages, config=config)
        text, issues, prepared_quotes = _brief_draft_text(
            message_text(reply),
            evidence,
            other_claims
            | {match_key(strip_citation_markers(s)) for s in split_sentences(accepted)},
            quotes,
        )
        if text and review is not None:
            stream({"type": "phase", "phase": "checking_citations"})
            earlier = [
                (current, strip_citation_markers(finding))
                for finding in split_sentences(accepted)
                if cited_numbers_in_order(finding)
            ]
            text, verification_issues = await _verify_draft_findings(
                text,
                prepared_quotes,
                [*existing, *earlier],
                assignment,
                subject,
                search_focus,
                evidence,
                config,
                review,
                review_scope,
                section,
            )
            issues.extend(verification_issues)
        if text:
            drafts.append(text)
            accepted, written_words = _combine_findings(drafts, target_words)
            if written_words >= minimum_words:
                break
        if not issues:
            issues.append(
                "Use relevant documented implementation or measurement and report the limits."
            )
    return await remove_repeated_brief_findings(
        accepted, config, review_scope, existing
    )
