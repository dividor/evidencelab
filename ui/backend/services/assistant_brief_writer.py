"""Build a Brief section from sentences checked against their own evidence."""

import asyncio
import re
from heapq import nlargest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from starlette.concurrency import run_in_threadpool

from ui.backend.auth.schemas import BriefSectionPrompt
from ui.backend.services.agent_passages import (
    passage_for_agent,
    passage_title_with_fields,
)
from ui.backend.services.assistant_grounding import (
    MAX_CONCURRENT_REVIEW_REQUESTS,
    EvidenceQuote,
    InvalidAssistantResponse,
    Passage,
    ReviewRequest,
    check_answer_citations,
    citation_check_batches,
    numbered_sentences,
    retain_supported_sentences,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.brief_evidence_selection import select_brief_evidence
from ui.backend.services.brief_excerpt_citations import cite_missing_excerpts
from ui.backend.services.brief_repetition import remove_repeated_brief_findings
from ui.backend.services.brief_section_prompt import brief_child_headings
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
_MISSING_CITATION = _DRAFT_FORMAT_ISSUE + " A sentence has no citation."


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
            if not labels:
                issues.append(_MISSING_CITATION)
                continue
            if any(label not in quotes for label in labels):
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


def _distinct_draft_sentences(draft: str):
    seen: set[str] = set()
    paragraphs = draft.split("\n\n")
    for index, paragraph in enumerate(paragraphs):
        for sentence in split_sentences(paragraph):
            plain = strip_citation_markers(sentence)
            key = match_key(plain)
            cited = bool(cited_numbers_in_order(sentence))
            if cited:
                if key in seen:
                    continue
                seen.add(key)
            yield index, sentence, len(plain.split()), cited


def _fit_section_to_target(draft: str, target: int | None) -> tuple[str, int]:
    """Stop at the nearest sentence boundary without skipping ahead in the argument."""
    paragraphs: dict[int, list[str]] = {}
    limit = ""
    remaining = target or float("inf")
    for index, sentence, words, cited in _distinct_draft_sentences(draft):
        if not cited:
            limit = limit or sentence
            continue
        # Finish this sentence if it brings the section closer to its target
        # and the result is still within the writing tolerance.
        if target and paragraphs and words > remaining + min(remaining, target * 0.15):
            break
        paragraphs.setdefault(index, []).append(sentence)
        remaining -= words
    blocks = [" ".join(sentences) for sentences in paragraphs.values()]
    if blocks and limit and len(limit.split()) <= remaining:
        blocks.append(limit)
    text = "\n\n".join(blocks)
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
    batches = list(citation_check_batches(sentences))
    concurrency = asyncio.Semaphore(MAX_CONCURRENT_REVIEW_REQUESTS)
    system = template.render(system=True)
    assignment = {
        "heading": section.outline[section.current].title,
        "topic": section.topic,
        "subject": subject,
        "guidance": section.focus,
        "instructions": section.instructions,
        "voice": section.voice_instructions,
        "introduces": brief_child_headings(section),
        "other_headings": [
            s.title for i, s in enumerate(section.outline) if i != section.current
        ],
        "whole_section": draft if len(batches) > 1 else "",
    }

    async def review_batch(batch: list[dict]) -> list[FindingScopeDecision]:
        request = template.render(
            **assignment,
            sentences=[
                _finding_for_scope(row, evidence, prepared_quotes, similar)
                for row in batch
            ],
        )
        async with concurrency:
            result: FindingScopeReview = await review(
                system, request, [], config, _FINDING_SCOPE
            )
        if sorted(row.id for row in result.reviews) != [row["id"] for row in batch]:
            raise InvalidAssistantResponse(
                "The scope check must assess each finding once"
            )
        return result.reviews

    decisions = await asyncio.gather(*(review_batch(batch) for batch in batches))
    decision = FindingScopeReview(reviews=[row for batch in decisions for row in batch])
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
        "preceding_sentence": row.get("preceding_sentence", ""),
        "supporting_quotes": [s.model_dump() for s in prepared_quotes.get(text, [])],
        "similar": similar.get(text, []),
        "sources": [
            {
                "title": passage_title_with_fields(evidence[label]),
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


def _revision_notes(text: str, sources: set[int]) -> str:
    """Only bring a previous finding into a revision with its own source available."""
    paragraphs = []
    for paragraph in text.split("\n\n"):
        notes = []
        for sentence in split_sentences(paragraph):
            cited = cited_numbers_in_order(sentence)
            if cited and sources.issuperset(cited):
                notes.append(strip_citation_markers(sentence))
        if notes:
            paragraphs.append(" ".join(notes))
    return "\n\n".join(paragraphs)


def _exceeds_word_budget(words: int, target: int | None) -> bool:
    return target is not None and words > target * 1.15


def _prefer_section_revision(
    words: int, previous_words: int, repair: str, minimum: float, issues: list[str]
) -> bool:
    """A complete, issue-free repair can replace a longer draft."""
    return words >= previous_words or (bool(repair) and words >= minimum and not issues)


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
    editorial_issues: list[str] | None = None,
) -> str:
    """Write independently sourced findings and optionally check their support."""
    if not evidence:
        return earlier_text
    evidence, (passages, quotes), subject = await select_brief_evidence(
        assignment, evidence, config, review_scope, target_words, earlier_text
    )
    if not evidence:
        return earlier_text
    template = assistant_prompt_templates.get_template("brief_evidence_draft.j2")
    introduces = brief_child_headings(section)
    system = template.render(
        system=True, target_words=target_words, introduces=introduces
    )
    stream = get_stream_writer()
    existing = _written_sibling_findings(section)
    sibling_matches = (
        await run_in_threadpool(_similar_findings, passages, existing)
        if existing
        else {}
    )
    selected_sources = {source for source, _ in quotes.values()}
    other_claims = {match_key(finding) for _, finding in existing}
    issues = list(editorial_issues or [])
    accepted = earlier_text
    # A known editorial defect may need a shorter correction.
    written_words = (
        0 if editorial_issues else len(strip_citation_markers(accepted).split())
    )
    minimum_words = target_words * 0.85 if target_words else 1
    repair_draft = ""
    draft_words = 0
    for attempt in range(2):
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=template.render(
                    assignment=assignment,
                    subject=subject,
                    writing_guide=writing_guide,
                    voice=section.voice_instructions,
                    introduces=introduces,
                    evidence=passages,
                    issues=issues,
                    repair_draft=repair_draft,
                    draft_words=draft_words,
                    accepted=_revision_notes(accepted, selected_sources),
                    target_words=target_words,
                    written_words=len(strip_citation_markers(accepted).split()),
                    sibling_matches=sibling_matches,
                )
            ),
        ]
        reply = await writer.ainvoke(messages, config=config)
        raw = await cite_missing_excerpts(
            message_text(reply), passages, set(quotes), config, review_scope
        )
        draft_words = len(strip_citation_markers(raw).split())
        text, issues, prepared_quotes = _brief_draft_text(
            raw,
            evidence,
            other_claims,
            quotes,
        )
        if text and review is not None:
            stream({"type": "phase", "phase": "checking_citations"})
            text, verification_issues = await _verify_draft_findings(
                text,
                prepared_quotes,
                existing,
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
        candidate, words = _fit_section_to_target(text, target_words)
        if _prefer_section_revision(
            words, written_words, repair_draft, minimum_words, issues
        ):
            accepted, written_words = candidate, words
        if attempt == 0 and _exceeds_word_budget(draft_words, target_words):
            repair_draft = raw
            continue
        if written_words >= minimum_words:
            break
    return await remove_repeated_brief_findings(
        accepted, config, review_scope, existing
    )
