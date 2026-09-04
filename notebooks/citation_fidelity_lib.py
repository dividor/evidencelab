"""Helpers for the citation-fidelity notebook.

Faithful Python ports of the frontend's citation logic, so the notebook
inspects a stored brief exactly the way the UI renders it:

- ``ui/frontend/src/components/citations/CitedContent.tsx``
  (``CITATION_REGEX``, ``normalizeClaimText``, ``parseSectionBreadcrumb``,
  the claim-key containment rule in ``resolveForClaim``)
- ``ui/frontend/src/components/brief/briefHighlights.ts``
  (``SENTENCE_SPLIT_RE``, ``extractClaimsForCitation``)

Kept as a plain module (not notebook cells) so the logic is unit-testable;
see ``tests/unit/test_citation_fidelity_lib.py``.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# `[1]`, `[1, 3]` — same as CITATION_REGEX in CitedContent.tsx.
CITATION_RE = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")

# Sentences end at ./!/? followed by whitespace; newlines (headings, list
# items) break sentences too — same as SENTENCE_SPLIT_RE in briefHighlights.ts.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# A leading "-- h1 > h2 -- " line is the chunk's heading breadcrumb.
SECTION_BREADCRUMB_RE = re.compile(r"^\s*--\s*(.+?)\s*--\s*$")

# Claim-key containment only applies to keys longer than this — same guard as
# resolveForClaim in CitedContent.tsx.
CLAIM_CONTAINMENT_MIN_CHARS = 24


def parse_citation_numbers(raw: str) -> List[int]:
    """``"1, 3"`` -> ``[1, 3]``."""
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def extract_cited_numbers(text: str) -> List[int]:
    """All unique citation indices appearing in the markdown, sorted."""
    cited = set()
    for match in CITATION_RE.finditer(text):
        cited.update(parse_citation_numbers(match.group(1)))
    return sorted(cited)


def normalize_claim_text(text: str) -> str:
    """Canonical claim key: markers and markdown stripped, lowercased.

    Must mirror ``normalizeClaimText`` exactly — stored ``claimMatches``
    entries are keyed by this form.
    """
    text = re.sub(r"\[(?:\d+,\s*)*\d+\]", "", text)
    text = re.sub(r"[#*_>`]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def parse_section_breadcrumb(text: str) -> Tuple[Optional[str], str]:
    """Split a stored excerpt into (breadcrumb, body).

    ``claimMatches`` offsets are relative to the *body*, i.e. the excerpt
    after this leading "-- … --" line.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    match = SECTION_BREADCRUMB_RE.match(lines[i].strip()) if i < len(lines) else None
    if match:
        body = "\n".join(lines[i + 1 :]).lstrip("\n")
        return match.group(1).strip(), body
    return None, text


def split_sentences(markdown: str) -> List[str]:
    """Section markdown -> claim-sized sentences (same splitter as the UI)."""
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(markdown) if s.strip()]


def sentences_citing(markdown: str, index: int) -> List[str]:
    """Every sentence of the section citing source ``index`` — the claims the
    UI highlights that source's excerpt against (``extractClaimsForCitation``).
    """
    marker = re.compile(rf"\[(?:\d+,\s*)*{index}(?:,\s*\d+)*\]")
    out = []
    seen = set()
    for sentence in split_sentences(markdown):
        if not marker.search(sentence):
            continue
        key = normalize_claim_text(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(sentence)
    return out


def find_claim_match(source: Dict[str, Any], sentence: str) -> Optional[Dict[str, Any]]:
    """The stored ``claimMatches`` entry for this citing sentence, if any.

    Same lookup as ``resolveForClaim``: exact key match, or containment for
    keys longer than 24 chars (sentence splitting differs slightly between
    enrichment time and render time).
    """
    key = normalize_claim_text(sentence)
    if not key:
        return None
    for entry in source.get("claimMatches") or []:
        claim = entry.get("claim", "")
        if claim == key:
            return entry
        if len(claim) > CLAIM_CONTAINMENT_MIN_CHARS and (claim in key or key in claim):
            return entry
    return None


@dataclass
class CitationPair:
    """One (citing sentence, cited source) pair — the unit of fidelity."""

    section_title: str
    sentence: str
    citation_index: int
    source: Optional[Dict[str, Any]] = None
    claim_match: Optional[Dict[str, Any]] = None
    matched_texts: List[str] = field(default_factory=list)

    @property
    def dangling(self) -> bool:
        """Cited index has no source in the section's ``sources[]``."""
        return self.source is None

    @property
    def has_stored_support(self) -> bool:
        return bool(self.claim_match and self.claim_match.get("matches"))


def extract_citation_pairs(section: Dict[str, Any]) -> List[CitationPair]:
    """All (sentence, source) citation pairs of one researched section."""
    markdown = section.get("content") or ""
    sources_by_index = {
        src["index"]: src
        for src in section.get("sources") or []
        if src.get("index") is not None
    }
    pairs: List[CitationPair] = []
    for sentence in split_sentences(markdown):
        for match in CITATION_RE.finditer(sentence):
            for index in parse_citation_numbers(match.group(1)):
                source = sources_by_index.get(index)
                pair = CitationPair(
                    section_title=section.get("title", ""),
                    sentence=sentence,
                    citation_index=index,
                    source=source,
                )
                if source is not None:
                    entry = find_claim_match(source, sentence)
                    if entry:
                        pair.claim_match = entry
                        _, body = parse_section_breadcrumb(source.get("text") or "")
                        for span in entry.get("matches") or []:
                            text = (
                                span.get("matchedText")
                                or body[span.get("start", 0) : span.get("end", 0)]
                            )
                            if text:
                                pair.matched_texts.append(text)
                pairs.append(pair)
    return pairs


def normalize_ws(text: str) -> str:
    """Whitespace-insensitive form for comparing excerpt vs. DB chunk text."""
    return re.sub(r"\s+", " ", text).strip()


def strip_citation_markers(text: str) -> str:
    """Remove ``[n]`` / ``[n, m]`` markers, collapsing the space they leave.

    Used to build the RAGAS ``response``: the statement generator would
    otherwise treat the markers as content.
    """
    stripped = CITATION_RE.sub("", text)
    stripped = re.sub(r"[ \t]+([.,;:!?])", r"\1", stripped)
    return re.sub(r"[ \t]{2,}", " ", stripped)


def cited_context_texts(section: Dict[str, Any]) -> List[str]:
    """The full excerpt text of every source the section actually cites.

    Deduped by ``chunkId`` in source order — these are the
    ``retrieved_contexts`` a faithfulness judge checks the section against.
    """
    cited = set(extract_cited_numbers(section.get("content") or ""))
    contexts: List[str] = []
    seen: set = set()
    for src in section.get("sources") or []:
        if src.get("index") not in cited:
            continue
        text = src.get("text") or ""
        chunk_key = src.get("chunkId") or text
        if not text or chunk_key in seen:
            continue
        seen.add(chunk_key)
        contexts.append(text)
    return contexts


def build_faithfulness_input(
    brief_query: str, section: Dict[str, Any]
) -> Dict[str, Any]:
    """One RAGAS Faithfulness sample for a researched section.

    ``user_input`` mirrors how the brief researches the section (topic +
    section title), ``response`` is the section markdown without citation
    markers, ``retrieved_contexts`` are the cited chunks' texts.
    """
    return {
        "user_input": f"{brief_query} — {section.get('title', '')}",
        "response": strip_citation_markers(section.get("content") or ""),
        "retrieved_contexts": cited_context_texts(section),
    }
