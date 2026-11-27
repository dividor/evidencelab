"""Resolve a saved evaluation draft's inline markers against its own source snapshot."""

import re

from ui.backend.services.brief_citation_model import (
    CITATION_RE,
    UNRESOLVED_RE,
    parse_marker_numbers,
)
from ui.backend.services.citation_fidelity import (
    match_key,
    split_sentences,
    strip_citation_markers,
)

_MARKER = re.compile(f"{CITATION_RE.pattern}|{UNRESOLVED_RE.pattern}")


def _claim(sentence, positions, references, reference_indices):
    parts = []
    cited = []
    start = 0
    for match in _MARKER.finditer(sentence):
        if match.start() > start:
            parts.append({"text": sentence[start : match.start()]})
        parts.append({"text": match.group(), "marker": True})
        labels = (
            [str(n) for n in parse_marker_numbers(match[1])]
            if match[1]
            else [f"?{match[2]}"]
        )
        for label in labels:
            if label not in reference_indices:
                reference_indices[label] = len(references)
                references.append(
                    {"label": label, "source_position": positions.get(label)}
                )
            cited.append(reference_indices[label])
        start = match.end()
    if start < len(sentence):
        parts.append({"text": sentence[start:]})
    return {"parts": parts, "references": list(dict.fromkeys(cited))}


def brief_claim_evidence(output):
    if not output or output.get("capability") != "brief":
        return None
    if output.get("written") is False or not (output.get("summary") or "").strip():
        return None
    positions = {
        str(source["index"]): offset
        for offset, source in enumerate(output.get("sources") or [])
        if source.get("index") is not None
    }
    references: list[dict] = []
    indices: dict[str, int] = {}
    paragraphs = [
        [
            _claim(sentence, positions, references, indices)
            for sentence in split_sentences(block)
        ]
        for block in re.split(r"\n\s*\n", output["summary"].strip())
    ]
    return {"paragraphs": paragraphs, "references": references}


def link_assessment_claims(assertions, evidence):
    """Identify literal quotations of the saved draft, without inferring a judge's intent."""
    claims = [
        match_key(strip_citation_markers("".join(p["text"] for p in claim["parts"])))
        for paragraph in evidence["paragraphs"]
        for claim in paragraph
    ]
    linked = []
    for assertion in assertions:
        reason = assertion.get("message") or ""
        quoted = [
            match_key(strip_citation_markers(phrase))
            for groups in re.findall(
                r"""“([^”]+)”|‘([^’]+)’|"([^"]+)"|(?<!\w)'(.+?)'(?!\w)""", reason
            )
            for phrase in groups
            if phrase
        ]
        mentioned = [
            i
            for i, claim in enumerate(claims)
            if any(phrase and f" {phrase} " in f" {claim} " for phrase in quoted)
        ]
        linked.append({**assertion, "quoted_claims": mentioned})
    return linked
