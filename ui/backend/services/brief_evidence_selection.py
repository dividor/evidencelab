"""Extract the parts of retrieved passages that belong in one Brief section."""

import logging

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ui.backend.services.agent_passages import passage_for_agent
from ui.backend.services.assistant_grounding import (
    InvalidAssistantResponse,
    Passage,
    ReviewRequest,
)
from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.citation_fidelity import split_sentences

logger = logging.getLogger(__name__)


class BriefPassageExcerpts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation: int
    subject_line: int
    finding_lines: list[int] = Field(min_length=1)


class BriefEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_subject: str = Field(min_length=1, max_length=500)
    passages: list[BriefPassageExcerpts]


_EVIDENCE_SELECTION = TypeAdapter(BriefEvidenceSelection)


def _check_selection(
    selection: BriefEvidenceSelection, entries: dict[int, list[str]]
) -> tuple[dict[int, list[str]], list[str]]:
    selected: dict[int, list[str]] = {}
    issues = []
    for row in selection.passages:
        lines = entries.get(row.citation)
        if lines is None:
            issues.append(f"Passage label {row.citation} is unavailable.")
            continue
        if not 0 <= row.subject_line < len(lines):
            issues.append(
                f"Subject line {row.subject_line} is unavailable in [{row.citation}]."
            )
            continue
        quotes = [
            lines[line_id] for line_id in row.finding_lines if 0 < line_id < len(lines)
        ]
        if len(quotes) != len(row.finding_lines):
            issues.append(
                f"Select finding lines from 1 to {len(lines) - 1} in [{row.citation}]."
            )
        if quotes:
            selected.setdefault(row.citation, [lines[row.subject_line]]).extend(quotes)
    return selected, issues


def _numbered_source_passages(entries: dict[int, list[str]]) -> str:
    groups = []
    for label, lines in entries.items():
        numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines))
        groups.append(f"Passage [{label}]\n{numbered}")
    return "\n\n".join(groups)


async def select_brief_evidence(
    assignment: str,
    evidence: dict[int, Passage],
    config: RunnableConfig,
    request_json: ReviewRequest,
    target_words: int | None,
    earlier_text: str = "",
) -> tuple[dict[int, Passage], tuple[str, dict[int, tuple[int, str]]], str]:
    """Use validated extracts for drafting and keep the full passages for verification."""
    template = assistant_prompt_templates.get_template("brief_evidence_selection.j2")
    system = template.render(system=True)
    entries = {
        label: [source["title"], *split_sentences(passage_for_agent(source["text"]))]
        for label, source in evidence.items()
    }
    passages = _numbered_source_passages(entries)
    accepted: dict[int, list[str]] = {}
    subject = ""
    issues: list[str] = []
    for _ in range(2):
        request = template.render(
            assignment=assignment,
            evidence=passages,
            allowed_labels=list(evidence),
            issues=issues,
            subject=subject,
            target_words=target_words,
            earlier_text=earlier_text,
        )
        response: BriefEvidenceSelection = await request_json(
            system, request, [], config, _EVIDENCE_SELECTION
        )
        selected, issues = _check_selection(response, entries)
        subject = subject or response.section_subject
        for label, quotes in selected.items():
            accepted.setdefault(label, [quotes[0]]).extend(quotes[1:])
        if not issues:
            break
        logger.info(
            "Brief evidence extraction accepted %d passages and found %d issues",
            len(accepted),
            len(issues),
        )
    if issues and not accepted:
        raise InvalidAssistantResponse(
            "The Brief could not extract evidence from its sources"
        )
    return (
        {
            label: {**evidence[label], "brief_subject_evidence": quotes[0]}
            for label, quotes in accepted.items()
        },
        _draft_excerpts(evidence, accepted),
        subject,
    )


def _draft_excerpts(evidence: dict[int, Passage], accepted: dict[int, list[str]]):
    """Give each selected source sentence its own short label for this drafting call."""
    quotes: dict[int, tuple[int, str]] = {}
    seen = set()
    groups = []
    for passage, lines in accepted.items():
        source = evidence[passage]
        group = [
            f"Source {passage}: {source['title']}",
            f"Subject: {lines[0]}",
        ]
        for line in lines[1:]:
            key = (source.get("doc_id") or passage, lines[0], line)
            if key in seen or line == source["title"]:
                continue
            seen.add(key)
            label = len(quotes) + 1
            quotes[label] = (passage, line)
            group.append(f"[{label}] {line}")
        if len(group) > 2:
            groups.append("\n".join(group))
    return "\n\n".join(groups), quotes
