"""Normalization helpers for parsed TOC lines."""

import logging
import re
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class TocNormalizeState:
    base_level: int
    stack: list[dict]
    last_major: int | None
    in_annex_section: bool


def normalize_toc_mixed_levels(toc_string: str) -> str:
    """
    Normalize mixed numbered/non-numbered TOC levels.

    - Numbered headings (e.g., "1.", "2.1") are aligned to a consistent depth.
    - Non-numbered headings under a numbered parent inherit the same shift.
    - The highest level is normalized to H1.
    """
    entries = _parse_toc_lines(toc_string)
    entries = _filter_out_of_sequence_major_headings(entries)
    parsed = [entry for entry in entries if entry.get("parsed")]
    if not parsed:
        return toc_string

    state = TocNormalizeState(
        base_level=min(entry["level"] for entry in parsed),
        stack=[],
        last_major=None,
        in_annex_section=False,
    )

    for entry in entries:
        if not entry.get("parsed"):
            continue

        _normalize_entry_level(entry, state)

    min_level = min(entry["level"] for entry in parsed)
    if min_level != 1:
        for entry in parsed:
            entry["level"] = max(1, entry["level"] - (min_level - 1))

    return _render_toc_entries(entries)


def _normalize_entry_level(entry: dict, state: TocNormalizeState) -> None:
    original_level = entry["level"]
    entry["orig_level"] = original_level

    _pop_stack_for_level(state.stack, original_level)

    title = entry["title"]
    if _is_annex_or_references_title(title):
        state.in_annex_section = True

    depth = _numbering_depth(title)
    if depth:
        if _should_skip_number_promotion(entry, state):
            return
        depth, state.last_major = _adjust_depth_for_major_sequence(
            title, depth, state.last_major
        )
        if depth:
            _apply_numbered_depth(entry, original_level, depth, state)
            return

    _apply_stack_delta(entry, original_level, state.stack)


def _pop_stack_for_level(stack: list[dict], original_level: int) -> None:
    while stack and original_level <= stack[-1]["orig_level"]:
        stack.pop()


def _should_skip_number_promotion(entry: dict, state: TocNormalizeState) -> bool:
    if entry.get("front"):
        # Never promote numbering inside front-matter sections.
        return True
    if state.in_annex_section:
        # Never promote numbering inside annex/references sections.
        return True
    return False


def _adjust_depth_for_major_sequence(
    title: str, depth: int, last_major: int | None
) -> tuple[int, int | None]:
    major_number = _parse_major_number(title)
    if (
        major_number is not None
        and last_major is not None
        and major_number < last_major
    ):
        # Ignore numbering when the major sequence regresses (e.g., 3 then 1),
        # so we don't promote it to a new top-level heading.
        return 0, last_major
    if major_number is not None:
        return depth, major_number
    return depth, last_major


def _parse_major_number(title: str) -> int | None:
    major_match = re.match(r"^\s*(\d+)", title)
    return int(major_match.group(1)) if major_match else None


def _apply_numbered_depth(
    entry: dict, original_level: int, depth: int, state: TocNormalizeState
) -> None:
    desired = state.base_level + depth - 1
    delta = desired - original_level
    entry["level"] = max(1, desired)
    state.stack.append({"orig_level": original_level, "delta": delta})


def _apply_stack_delta(entry: dict, original_level: int, stack: list[dict]) -> None:
    if stack:
        entry["level"] = max(1, original_level + stack[-1]["delta"])


def _filter_out_of_sequence_major_headings(entries: List[dict]) -> List[dict]:
    """
    Drop major headings like "42." when a sequential major numbering
    pattern is already established (e.g., 1, 2, 3, ...).
    """
    filtered: List[dict] = []
    last_major: int | None = None
    for entry in entries:
        if not entry.get("parsed"):
            filtered.append(entry)
            continue

        title = entry.get("title", "")
        major_number = _parse_major_heading_number(title)
        if major_number is not None:
            last_major, should_skip = _update_major_sequence(major_number, last_major)
            if should_skip:
                logger.info(
                    "  ⚠ Skipping out-of-sequence major heading: %s",
                    title[:80],
                )
                continue

        filtered.append(entry)

    return filtered


def _parse_toc_lines(toc_string: str) -> List[dict]:
    entries: List[dict] = []
    pattern = re.compile(
        r"^(?P<indent>\s*)(?P<marker>x\s+)?\s*\[H(?P<level>\d+)\]"
        r"\s*(?P<title>.*?)\s*\|\s*page\s*(?P<page>\d+)"
        r"(?:\s*\((?P<roman>[^)]+)\))?\s*(?P<front>\[Front\])?\s*$"
    )
    for raw_line in toc_string.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = pattern.match(line)
        if not match:
            entries.append(
                {
                    "raw": line,
                    "level": None,
                    "title": "",
                    "page": "",
                    "prefix": "",
                    "parsed": False,
                }
            )
            continue
        entries.append(
            {
                "raw": line,
                "level": int(match.group("level")),
                "title": match.group("title").strip(),
                "page": match.group("page"),
                "prefix": match.group("marker") or "",
                "roman": match.group("roman"),
                "front": bool(match.group("front")),
                "parsed": True,
            }
        )
    return entries


def _render_toc_entries(entries: List[dict]) -> str:
    rendered_lines: List[str] = []
    for entry in entries:
        if not entry.get("parsed"):
            rendered_lines.append(entry["raw"])
            continue
        level = entry["level"]
        indent = "  " * (level - 1)
        prefix = entry.get("prefix", "")
        title = entry["title"]
        page = entry["page"]
        roman = entry.get("roman")
        front = entry.get("front")
        roman_suffix = f" ({roman})" if roman else ""
        front_suffix = " [Front]" if front else ""
        rendered_lines.append(
            f"{prefix}{indent}[H{level}] {title} | page {page}{roman_suffix}{front_suffix}"
        )
    return "\n".join(rendered_lines)


def _numbering_depth(title: str) -> int:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", title)
    if not match:
        return 0
    return match.group(1).count(".") + 1


def _is_annex_or_references_title(title: str) -> bool:
    normalized = title.strip().lower()
    return bool(
        re.search(
            r"\b(annex|annexe|annexes|appendix|appendices|references|bibliography)\b",
            normalized,
        )
    )


def _parse_major_heading_number(title: str) -> int | None:
    if _numbering_depth(title) != 1:
        return None
    match = re.match(r"^\s*(\d+)\.", title)
    if not match:
        return None
    return int(match.group(1))


def _update_major_sequence(
    number: int, last_major: int | None
) -> tuple[int | None, bool]:
    if last_major is None:
        return number, False
    if number == last_major + 1:
        return number, False
    if number > last_major and number != last_major + 1:
        return last_major, True
    return last_major, False
