"""Brief citations, shared vocabulary: the stored shapes, constants, errors,
marker parsing and the small lookups every other brief-citation module uses.

See ``brief_citations`` (the facade) for what the modules do together.
"""

import re
import time
from typing import Any, Dict, Iterable, List, Optional

CITATIONS_VERSION = 2


GROUPINGS = ("passage", "document-multiple", "document-single")


GROUPING_PASSAGE, GROUPING_DOC_MULTIPLE, GROUPING_DOC_SINGLE = GROUPINGS


RUN_MODES = ("generate", "edit", "update", "condense", "manual")


RUN_CURRENT = "current"


RUN_SUPERSEDED = "superseded"


RUN_REJECTED = "rejected"


SOURCES_EXACT = "exact"


SOURCES_TRIMMED = "cited-without-excerpt"


REASON_NO_SOURCE = "no-source"


REASON_NO_CHUNK = "no-chunk-id"


# Earlier runs kept (trimmed) besides the exact latest/current run.
RETAINED_TRIMMED_RUNS = 4


# Same ceiling the API applies to the stored JSON
# (auth.schemas._MAX_RESEARCH_JSONB_SIZE); kept literal so this module stays
# importable without the FastAPI stack.
MAX_CONTENT_CHARS = 10_000_000


# `[1]`, `[1, 3]` — the citation marker the renderer resolves (CitedContent.tsx).
CITATION_RE = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")


# `[?7]` — an unresolved marker, left visible by the renumbering.
UNRESOLVED_RE = re.compile(r"\[\?(\d+)\]")


# Two markers side by side carrying the same number(s): `[1][1]`, `[1] [1]`.
ADJACENT_DUPLICATE_RE = re.compile(r"\[(\d+(?:, \d+)*)\]\s*\[\1\]")


# What a source record contributes to the brief-wide list when first registered.
DISPLAY_FIELDS = (
    "chunkId",
    "docId",
    "title",
    "text",
    "score",
    "page",
    "bbox",
    "headings",
    "pdfUrl",
    "reportUrl",
)


# Fields a later record of the same chunk may fill in when the first was empty.
FILLABLE_FIELDS = ("text", "page", "pdfUrl", "reportUrl", "headings", "bbox")


# Section fields the client owns (structure and settings); everything about
# citations is taken from the stored row, never from a client save.
SECTION_STRUCTURE_FIELDS = (
    "title",
    "level",
    "status",
    "guidance",
    "voiceId",
    "targetWords",
    "introHeadingWarning",
    "lastResearchedAt",
    "sample",
)


BRIEF_SETTING_FIELDS = (
    "id",
    "title",
    "query",
    "date",
    "sectionCount",
    "outlineLog",
    "numberHeadings",
    "activityId",
    "voiceId",
    "targetWords",
    "instructions",
)


# Run fields returned inline by the read model; content and sources are
# fetched one run at a time.
RUN_SUMMARY_FIELDS = (
    "id",
    "mode",
    "at",
    "runId",
    "question",
    "instruction",
    "status",
    "sourcesRetained",
    "mapping",
    "unresolved",
    "rejected",
)


class BriefCitationError(ValueError):
    """A citation operation that cannot be applied (bad section, run, grouping…)."""


class LegacyBriefError(BriefCitationError):
    """The brief predates citation format 2 and has not been converted."""


class BriefTooLargeError(BriefCitationError):
    """Applying the change would push the brief over the stored-JSON ceiling."""


def _now_ms(now_ms: Optional[int]) -> int:
    return int(now_ms if now_ms is not None else time.time() * 1000)


def parse_marker_numbers(raw: str) -> List[int]:
    """``"1, 3"`` -> ``[1, 3]``."""
    return [int(part) for part in raw.split(",") if part.strip().isdigit()]


def cited_numbers_in_order(text: str) -> List[int]:
    """Every number cited in the markdown, unique, in order of first appearance."""
    seen: List[int] = []
    for match in CITATION_RE.finditer(text or ""):
        for number in parse_marker_numbers(match.group(1)):
            if number not in seen:
                seen.append(number)
    return seen


def _normalise_heading_line(line: str) -> str:
    """Compare a line against a heading title: drop hashes, numbering, emphasis."""
    line = re.sub(r"^#{1,6}\s+", "", line)
    line = re.sub(r"^\d+(\.\d+)*\.?\s+", "", line)
    return re.sub(r"[*_`]", "", line).strip().lower()


def strip_leading_title(markdown: str, title: str) -> str:
    """Drop a leading title line the model repeated above its prose.

    The brief renders the section's own (editable) heading above the text,
    so a first line that is a markdown heading, or simply repeats the title,
    is removed together with the blank lines that followed it.
    """
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return markdown
    first = lines[i]
    is_heading = re.match(r"^#{1,6}\s+", first) is not None
    repeats = bool(title) and _normalise_heading_line(first) == _normalise_heading_line(
        title
    )
    if not is_heading and not repeats:
        return markdown
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:])


def collapse_adjacent_duplicates(content: str) -> str:
    """``[1][1]`` -> ``[1]`` (repeatedly), as per-document numbering produces."""
    out = content
    while True:
        collapsed = ADJACENT_DUPLICATE_RE.sub(r"[\1]", out)
        if collapsed == out:
            return out
        out = collapsed


def require_current_format(content: Dict[str, Any]) -> None:
    """Refuse a brief stored before citation format 2 (no silent reading)."""
    if (content or {}).get("citationsVersion") != CITATIONS_VERSION:
        raise LegacyBriefError(
            "Brief predates citation format 2; run the conversion "
            "(scripts/fixes/convert_brief_citations.py)"
        )


def _ensure_lists(content: Dict[str, Any]) -> None:
    content.setdefault("sources", [])
    content.setdefault("sections", [])
    content.setdefault("referenceGrouping", GROUPING_PASSAGE)
    for section in content["sections"]:
        section.setdefault("runs", [])
        section.setdefault("audit", [])


def find_section(content: Dict[str, Any], section_id: str) -> Dict[str, Any]:
    for section in content.get("sections") or []:
        if section.get("id") == section_id:
            return section
    raise BriefCitationError(f"Unknown section: {section_id}")


def find_run(section: Dict[str, Any], run_id: str) -> Optional[Dict[str, Any]]:
    for run in section.get("runs") or []:
        if run.get("id") == run_id:
            return run
    return None


def current_run(section: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    run_id = section.get("currentRunId")
    return find_run(section, run_id) if run_id else None


def _next_id(prefix: str, ids: Iterable[str]) -> str:
    highest = 0
    for existing in ids:
        suffix = str(existing or "")[len(prefix) :]
        if str(existing or "").startswith(prefix) and suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1}"


def _all_run_ids(content: Dict[str, Any]) -> List[str]:
    return [
        run["id"]
        for section in content.get("sections") or []
        for run in section.get("runs") or []
    ]


def _sources_by_id(content: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {src["id"]: src for src in content.get("sources") or []}


def is_visible(section: Dict[str, Any]) -> bool:
    """A section takes part in the numbering when it is done and has content."""
    run = current_run(section)
    return section.get("status") == "done" and bool(run and (run.get("content") or ""))


def _display_record(agent_source: Dict[str, Any]) -> Dict[str, Any]:
    return {key: agent_source[key] for key in DISPLAY_FIELDS if key in agent_source}


def _fill_missing(entry: Dict[str, Any], agent_source: Dict[str, Any]) -> None:
    """A later record of the same chunk fills fields the first left empty."""
    for key in FILLABLE_FIELDS:
        if not entry.get(key) and agent_source.get(key):
            entry[key] = agent_source[key]


def unresolved_markers(
    text: str, mapping: Dict[str, str], rejected: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Cited numbers the mapping cannot resolve, with why."""
    rejected_indices = {r.get("index") for r in rejected}
    return [
        {
            "n": number,
            "reason": (
                REASON_NO_CHUNK if number in rejected_indices else REASON_NO_SOURCE
            ),
        }
        for number in cited_numbers_in_order(text)
        if str(number) not in mapping
    ]
