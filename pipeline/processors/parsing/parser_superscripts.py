"""Superscript detection and annotation helpers for parsing."""

import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)


def _is_superscript_token(text: str) -> bool:
    return (len(text) <= 3 and text.isdigit()) or text in ["*", "†", "‡", "§"]


def _median_span_size(spans: list) -> float | None:
    sizes = [span["size"] for span in spans if span["text"].strip()]
    if not sizes:
        return None
    sizes.sort()
    return sizes[len(sizes) // 2]


def _get_block_reference(spans: list, median_size: float) -> Tuple[float, bool]:
    normal_spans = [
        span for span in spans if 0.9 * median_size <= span["size"] <= 1.1 * median_size
    ]
    if not normal_spans:
        block_ref_y = sum(
            (span["bbox"][1] + span["bbox"][3]) / 2 for span in spans
        ) / len(spans)
        return block_ref_y, False
    if "origin" in normal_spans[0]:
        block_ref_y = sum(span["origin"][1] for span in normal_spans) / len(
            normal_spans
        )
        return block_ref_y, True
    block_ref_y = sum(
        (span["bbox"][1] + span["bbox"][3]) / 2 for span in normal_spans
    ) / len(normal_spans)
    return block_ref_y, False


def _build_regex_pattern(prev_ctx: str, token: str, next_ctx: str) -> str:
    safe_token = re.escape(token)
    safe_prev = re.escape(prev_ctx).replace(r"\ ", r"\s+").replace(" ", r"\s+")
    safe_next = re.escape(next_ctx).replace(r"\ ", r"\s+").replace(" ", r"\s+")
    pattern_parts = []
    if not safe_prev and token and token[0].isalnum():
        pattern_parts.append(r"\b")
    if safe_prev:
        pattern_parts.append(safe_prev)
        pattern_parts.append(r"\s*")
    pattern_parts.append(f"({safe_token})")
    if safe_next:
        pattern_parts.append(r"\s*")
        pattern_parts.append(safe_next)
    if not safe_next and token and token[-1].isalnum():
        pattern_parts.append(r"\b")
    return "".join(pattern_parts)


def _build_superscript_rule(
    spans: list,
    index: int,
    median_size: float,
    block_ref_y: float,
    use_baseline: bool,
) -> Tuple[str, str] | None:
    if index == 0:
        return None
    span = spans[index]
    text = span["text"].strip()
    if not text or not _is_superscript_token(text):
        return None
    if span["size"] >= median_size * 0.85:
        return None
    if use_baseline and "origin" in span:
        span_y = span["origin"][1]
        elevation = block_ref_y - span_y
        threshold = 0.15 * median_size
    else:
        span_y = (span["bbox"][1] + span["bbox"][3]) / 2
        elevation = block_ref_y - span_y
        threshold = 0.2 * median_size
    if elevation < threshold:
        return None
    prev_text = spans[index - 1]["text"] if index > 0 else ""
    next_text = spans[index + 1]["text"] if index < len(spans) - 1 else ""
    prev_ctx = prev_text[-10:].strip() if prev_text else ""
    next_ctx = next_text[:10].strip() if next_text else ""
    return _build_regex_pattern(prev_ctx, text, next_ctx), text


def detect_superscripts_via_geometry(
    parser, filepath: str
) -> Dict[int, List[Tuple[str, str]]]:
    """Detect potential superscript tokens in PDF using geometry (PyMuPDF)."""
    if not parser.enable_superscripts:
        return {}

    superscripts: Dict[int, List[Tuple[str, str]]] = {}
    try:
        doc = fitz.open(filepath)
        for page_num, page in enumerate(doc, 1):
            rules = _extract_rules_from_page(page)
            if rules:
                superscripts[page_num] = rules
        doc.close()
        _log_superscript_summary(superscripts)
        return superscripts
    except Exception as exc:
        logger.warning("  Failed to detect superscripts via geometry: %s", exc)
        return {}


def _extract_rules_from_page(page) -> List[Tuple[str, str]]:
    rules: List[Tuple[str, str]] = []
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        rules.extend(_extract_rules_from_block(block))
    return rules


def _extract_rules_from_block(block: dict) -> List[Tuple[str, str]]:
    if "lines" not in block:
        return []
    rules: List[Tuple[str, str]] = []
    for line in block.get("lines", []):
        rules.extend(_extract_rules_from_line(line))
    return rules


def _extract_rules_from_line(line: dict) -> List[Tuple[str, str]]:
    spans = line.get("spans", [])
    if not spans:
        return []
    median_size = _median_span_size(spans)
    if not median_size:
        return []
    block_ref_y, use_baseline = _get_block_reference(spans, median_size)
    rules: List[Tuple[str, str]] = []
    for i, _span in enumerate(spans):
        rule = _build_superscript_rule(spans, i, median_size, block_ref_y, use_baseline)
        if rule:
            rules.append(rule)
    return rules


def _log_superscript_summary(superscripts: Dict[int, List[Tuple[str, str]]]) -> None:
    if superscripts:
        logger.info(
            "  Detected superscripts on %s pages using geometric context",
            len(superscripts),
        )


def log_superscript_detection(
    superscripts: Dict[int, List[Tuple[str, str]]], filepath: str
) -> None:
    """Log superscript detection diagnostics."""
    logger.debug(
        "DEBUG: _detect_superscripts_via_geometry found %s pages with items for %s",
        len(superscripts),
        filepath,
    )
    if superscripts:
        logger.debug("DEBUG: Superscripts dict keys: %s", list(superscripts.keys()))


def flatten_superscripts(
    superscripts: Dict[int, List[Tuple[str, str]]]
) -> List[Tuple[str, str]]:
    """Flatten superscripts dict into a list of rules."""
    all_rules: List[Tuple[str, str]] = []
    for page_rules in superscripts.values():
        all_rules.extend(page_rules)
    return all_rules


def apply_superscripts_to_markdown(
    parser, markdown_path: Path, superscripts: Dict[int, List[Tuple[str, str]]]
) -> None:
    """Apply superscript annotations to markdown."""
    all_rules = flatten_superscripts(superscripts)
    logger.debug("DEBUG: Applying %s superscripts to %s", len(all_rules), markdown_path)
    with open(markdown_path, "r", encoding="utf-8") as file_handle:
        content = file_handle.read()

    replacement_template = (
        "<sup>{}</sup>" if parser.superscript_mode == "html" else "^{}"
    )
    known_tokens = {token for _, token in all_rules}
    for regex_pattern, token in all_rules:
        try:
            annotated_token = replacement_template.format(token)

            def replace_func(match, repl=annotated_token):
                return match.group(0).replace(match.group(1), repl, 1)

            content = re.sub(regex_pattern, replace_func, content)
        except re.error:
            pass

    known_tokens = {token for _, token in all_rules}
    if known_tokens:

        def replace_def(match):
            num_str = match.group(1)
            if num_str in known_tokens:
                return f"^{num_str} "
            return match.group(0)

        content = re.sub(r"^(\d+)\s", replace_def, content, flags=re.MULTILINE)

    with open(markdown_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(content)


def apply_superscripts_to_docling_items(
    parser, document: DoclingDocument, superscripts: Dict[int, List[Tuple[str, str]]]
) -> None:
    """Apply superscripts to Docling document items for JSON/chunk validity."""
    if not superscripts:
        return
    all_rules = flatten_superscripts(superscripts)
    if not all_rules:
        return

    replacement_template = (
        "<sup>{}</sup>" if parser.superscript_mode == "html" else "^{}"
    )
    for item, _ in document.iterate_items():
        if hasattr(item, "text") and item.text:
            original_text = item.text
            modified_text = original_text

            for regex_pattern, token in all_rules:
                try:
                    annotated_token = replacement_template.format(token)

                    def replace_func_item(match, repl=annotated_token):
                        return match.group(0).replace(match.group(1), repl, 1)

                    modified_text = re.sub(
                        regex_pattern,
                        replace_func_item,
                        modified_text,
                    )
                except re.error:
                    pass

            if modified_text != original_text:
                item.text = modified_text
