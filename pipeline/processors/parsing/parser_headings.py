"""Heading detection and hierarchy helpers."""

import contextlib
import copy
import io
import logging
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TextIO, Tuple, cast

import fitz  # PyMuPDF
from hierarchical.postprocessor import ResultPostprocessor

logger = logging.getLogger(__name__)


def apply_hierarchical_postprocessor(_parser, result: Any, filepath: Path) -> None:
    """
    Apply hierarchical postprocessor with revert if it removes all headers.

    The ResultPostprocessor tries to extract TOC from PDF metadata first.
    If metadata extraction removes most headers, we revert to original Docling headers.
    """
    headers_before = sum(
        1
        for item, _ in result.document.iterate_items()
        if type(item).__name__ == "SectionHeaderItem"
    )

    logger.info("  Docling found: %s headers before postprocessing", headers_before)
    _log_header_samples(result, label="before")

    original_document = copy.deepcopy(result.document)

    missing_heading_count = 0

    class _TeeStream:
        def __init__(self, original, buffer):
            self.original = original
            self.buffer = buffer

        def write(self, text):
            self.buffer.write(text)
            return self.original.write(text)

        def flush(self):
            self.buffer.flush()
            return self.original.flush()

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    stdout_tee = _TeeStream(sys.stdout, stdout_buffer)
    stderr_tee = _TeeStream(sys.stderr, stderr_buffer)

    with contextlib.redirect_stdout(
        cast(TextIO, stdout_tee)
    ), contextlib.redirect_stderr(cast(TextIO, stderr_tee)):
        if ResultPostprocessor is not None:
            ResultPostprocessor(result, source=filepath, raise_on_error=False).process()
        else:
            logger.warning(
                "ResultPostprocessor not available, skipping hierarchical processing"
            )

    captured = stdout_buffer.getvalue() + stderr_buffer.getvalue()
    missing_heading_count += captured.count("Following heading was not found")
    missing_heading_count += (
        captured.count("Could not find title") if "mentioned in TOC" in captured else 0
    )

    headers_after = sum(
        1
        for item, _ in result.document.iterate_items()
        if type(item).__name__ == "SectionHeaderItem"
    )

    logger.info("  Headers after postprocessing: %s", headers_after)
    _log_header_samples(result, label="after")

    missing_threshold = max(5, int(headers_before * 0.05))
    if missing_heading_count >= missing_threshold:
        logger.info(
            "  ⚠ Hierarchical postprocessor reported %s missing headings "
            "(threshold: %s). Reverting to Docling headers...",
            missing_heading_count,
            missing_threshold,
        )
        result.document = original_document
        logger.info("  ✓ Reverted to %s original Docling headers", headers_before)
        return

    if headers_before > 10 and headers_after < headers_before * 0.2:
        logger.info(
            "  ⚠ Hierarchical postprocessor removed most headers "
            "(%s → %s). Reverting to Docling headers...",
            headers_before,
            headers_after,
        )
        result.document = original_document
        logger.info("  ✓ Reverted to %s original Docling headers", headers_before)


def check_if_hierarchy_exists(result: Any) -> bool:
    """Check if document has meaningful heading hierarchy."""
    levels = set()
    for item, _ in result.document.iterate_items():
        if type(item).__name__ == "SectionHeaderItem":
            level = getattr(item, "level", -1)
            levels.add(level)

    return len(levels) > 1 and -1 not in levels


def _log_header_samples(result: Any, label: str, limit: int = 30) -> None:
    headers = []
    for item, _ in result.document.iterate_items():
        if type(item).__name__ != "SectionHeaderItem":
            continue
        text = getattr(item, "text", "").strip()
        level = getattr(item, "level", None)
        page = "?"
        prov = getattr(item, "prov", None)
        if prov:
            for prov_item in prov:
                if hasattr(prov_item, "page_no"):
                    page = prov_item.page_no
                    break
        headers.append((level, page, text))
        if len(headers) >= limit:
            break

    if not headers:
        return

    logger.info("  Header sample %s (level/page/text):", label)
    for level, page, text in headers:
        logger.info("    H%s p%s %s", level, page, text[:120])


def infer_level_from_numbering(text: str) -> Optional[int]:
    """Infer heading level from section numbering pattern."""
    text = text.strip()

    numbered = re.match(r"^(\d+)\.(\d+)?\.?(\d+)?\.?(\d+)?\.?(\d+)?", text)
    if numbered:
        groups = [g for g in numbered.groups() if g is not None]
        if len(groups) == 1 and int(groups[0]) >= 50:
            return None
        return min(len(groups), 6)

    if re.match(r"^(EQ|Figure|Table|Box)\s+\d+", text, re.IGNORECASE):
        return 3

    return None


def get_top_level_sections() -> Set[str]:
    """Known top-level section names."""
    return {
        "abstract",
        "contents",
        "acknowledgements",
        "abbreviations",
        "executive summary",
        "introduction",
        "background",
        "methodology",
        "findings",
        "conclusions",
        "recommendations",
        "bibliography",
        "references",
        "annexes",
        "appendices",
        "list of",
    }


def extract_hybrid_headings(
    _parser, filepath: str, body_size: float
) -> List[Dict[str, Any]]:
    """
    Extract headings using hybrid approach: PyMuPDF fonts + numbering patterns.
    """
    doc = fitz.open(filepath)
    headings: List[Dict[str, Any]] = []
    top_sections = get_top_level_sections()

    for page_num, page in enumerate(doc, 1):
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" not in block:
                continue

            full_text, dominant_size = _extract_block_text_and_font(block)
            if not full_text or dominant_size is None:
                continue
            if not _is_heading_text_size(full_text):
                continue

            level, method = _determine_heading_level(
                full_text, dominant_size, body_size, top_sections
            )
            if level is None:
                continue
            headings.append(
                {
                    "text": full_text,
                    "level": level,
                    "page": page_num,
                    "method": method,
                }
            )

    doc.close()
    return headings


def _extract_block_text_and_font(block: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    block_texts = []
    block_fonts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = span["text"].strip()
            if text:
                block_texts.append(text)
                block_fonts.append(
                    {
                        "size": round(span["size"], 1),
                        "font": span["font"],
                        "bold": "bold" in span["font"].lower(),
                    }
                )
    if not block_texts or not block_fonts:
        return "", None
    full_text = " ".join(block_texts)
    font_sizes = [font["size"] for font in block_fonts]
    dominant_size = max(set(font_sizes), key=font_sizes.count)
    return full_text, dominant_size


def _is_heading_text_size(text: str) -> bool:
    length = len(text)
    return 5 <= length <= 300


def _determine_heading_level(
    text: str, dominant_size: float, body_size: float, top_sections: Set[str]
) -> Tuple[Optional[int], Optional[str]]:
    if dominant_size > body_size + 2:
        if dominant_size >= 25:
            return 1, "font"
        if dominant_size >= 20:
            return 2, "font"
        if dominant_size >= 16:
            return 3, "font"
        if dominant_size >= 14:
            return 4, "font"
    inferred = infer_level_from_numbering(text)
    if inferred:
        return inferred, "numbering"
    if any(section in text.lower() for section in top_sections):
        return 1, "keyword"
    return None, None


def apply_hybrid_heading_detection(parser, result: Any, filepath: Path) -> bool:
    """Apply hybrid heading detection to Docling document."""
    try:
        body_size = _detect_body_text_size(filepath)
        if body_size is None:
            logger.warning("  Could not determine body text size")
            return False
        logger.debug("  Body text size: %spt", body_size)

        hybrid_headings = extract_hybrid_headings(parser, str(filepath), body_size)

        if not hybrid_headings:
            logger.info("  Hybrid detection found no headings")
            return False

        hybrid_levels = set(h["level"] for h in hybrid_headings)
        if len(hybrid_levels) <= 1:
            logger.info("  Hybrid detection also found no hierarchy")
            return False

        logger.info(
            "  ✓ Hybrid detection found %s headings with %s levels",
            len(hybrid_headings),
            len(hybrid_levels),
        )

        heading_map = _build_heading_map(hybrid_headings)
        updated_count = _apply_heading_map(result, heading_map)

        logger.info(
            "  ✓ Updated %s heading levels using hybrid detection", updated_count
        )
        return True

    except Exception as exc:
        logger.warning("  Hybrid heading detection failed: %s", exc)
        logger.debug(traceback.format_exc())
        return False


def _detect_body_text_size(filepath: Path) -> Optional[float]:
    doc = fitz.open(str(filepath))
    font_dist: Dict[float, int] = {}
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        size = round(span["size"], 1)
                        font_dist[size] = font_dist.get(size, 0) + 1
    doc.close()
    if not font_dist:
        return None
    return max(font_dist.items(), key=lambda x: x[1])[0]


def _build_heading_map(headings: List[Dict[str, Any]]) -> Dict[str, int]:
    heading_map = {}
    for heading in headings:
        key = heading["text"].lower().strip()[:100]
        heading_map[key] = heading["level"]
    return heading_map


def _apply_heading_map(result: Any, heading_map: Dict[str, int]) -> int:
    updated_count = 0
    for item, _ in result.document.iterate_items():
        if type(item).__name__ != "SectionHeaderItem":
            continue
        text = item.text.strip()
        key = text.lower().strip()[:100]
        if key in heading_map:
            updated_count += _maybe_update_level(item, heading_map[key])
            continue
        updated_count += _try_fuzzy_update(item, key, heading_map)
    return updated_count


def _maybe_update_level(item: Any, new_level: int) -> int:
    old_level = getattr(item, "level", -1)
    if old_level != new_level and new_level >= 1:
        item.__dict__["level"] = new_level
        return 1
    return 0


def _try_fuzzy_update(item: Any, key: str, heading_map: Dict[str, int]) -> int:
    if len(key) <= 10:
        return 0
    for hybrid_key, level in heading_map.items():
        if key in hybrid_key or hybrid_key in key:
            return _maybe_update_level(item, level)
    return 0
