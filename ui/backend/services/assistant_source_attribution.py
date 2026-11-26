"""Check concrete source details against the title and document metadata."""

import re
from typing import Any

from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.citation_fidelity import match_key

SourcePassages = dict[int, dict[str, Any]]

_COUNTRY_LEAD = re.compile(
    r"^(?:in|(?:the |an )?(?:mid[ -]?term |end[ -]?line )?evaluation (?:in|of|from))"
    r"\s+(?:the )?",
    re.IGNORECASE,
)
_REPORT_STAGE = re.compile(
    r"^(?:the |an )?(baseline|mid[ -]?(?:term|line)|end[ -]?line|final)\s+evaluation\b",
    re.IGNORECASE,
)


def _country_attributions(
    sentences: list[dict], evidence: SourcePassages
) -> dict[int, str]:
    """Reject explicit country attributions that contradict report metadata."""
    countries = {
        index: _country_names(passage.get("country"))
        for index, passage in evidence.items()
    }
    known = set().union(*countries.values())
    mismatches = {}
    for row in sentences:
        if not (row["citations"] and (match := _COUNTRY_LEAD.match(row["text"]))):
            continue
        remainder = f"{match_key(row['text'][match.end():])} "
        location = max(
            (name for name in known if remainder.startswith(f"{name} ")),
            key=len,
            default="",
        )
        if not location:
            continue
        cited = row["citations"]
        located = f" {location} "
        if any(
            not countries[index]
            or location in countries[index]
            or located in f" {match_key(evidence[index]['title'])} "
            or located in f" {match_key(passage_for_agent(evidence[index]['text']))} "
            for index in cited
        ):
            continue
        labels = ", ".join(f"[{index}]" for index in cited)
        mismatches[row["id"]] = (
            f"Sentence {row['id']}: {labels} do not identify {location} as the location. "
            "Use evidence for the stated location or correct the location in the claim."
        )
    return mismatches


def _country_names(value: str | list[str] | None) -> set[str]:
    labels = re.split(r"[;|]", value) if isinstance(value, str) else value or []
    return {match_key(label).removeprefix("the ") for label in labels if label.strip()}


def _report_stage(text: str) -> str:
    match = _REPORT_STAGE.match(text)
    if not match:
        return ""
    label = match[1].lower()
    if label.startswith("mid"):
        return "midterm"
    return "baseline" if label == "baseline" else "endline"


def _stage_attributions(
    sentences: list[dict], evidence: SourcePassages
) -> dict[int, str]:
    mismatches = {}
    for row in sentences:
        stage = _report_stage(row["text"])
        if not stage or len(row["citations"]) != 1:
            continue
        index = row["citations"][0]
        actual = _report_stage(evidence[index]["title"])
        if actual and actual != stage:
            mismatches[row["id"]] = (
                f"Sentence {row['id']}: [{index}] is a {actual} evaluation. "
                f"Use the stage documented by the report instead of {stage}."
            )
    return mismatches


def source_attribution_issues(
    sentences: list[dict], evidence: SourcePassages
) -> dict[int, str]:
    return {
        **_country_attributions(sentences, evidence),
        **_stage_attributions(sentences, evidence),
    }
