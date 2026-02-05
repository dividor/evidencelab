"""Fallback TOC generation helpers."""

import logging
import re
from pathlib import Path
from typing import List

import fitz

from pipeline.processors.parsing.toc_docling import _is_docling_toc_low_quality

logger = logging.getLogger(__name__)


def generate_fallback_toc(_parser, markdown_path: Path) -> List[str]:
    """Generate TOC from markdown when Docling detects no section headers."""
    toc_lines: List[str] = []
    try:
        content = _read_markdown(markdown_path)
        toc_lines = _build_fallback_toc_lines(content)

    except Exception as exc:
        logger.warning("Fallback TOC generation failed: %s", exc)

    return toc_lines


def generate_pymupdf_toc(_parser, filepath: str) -> List[str]:
    """Generate TOC from PDF outline using PyMuPDF."""
    toc_lines: List[str] = []
    try:
        with fitz.open(filepath) as doc:
            toc_entries = doc.get_toc(simple=True) or []
    except Exception as exc:
        logger.warning("PyMuPDF TOC generation failed: %s", exc)
        return toc_lines

    for level, title, page in toc_entries:
        cleaned_title = (title or "").strip()
        if not cleaned_title:
            continue
        indent = "  " * (max(level, 1) - 1)
        toc_lines.append(
            f"{indent}[H{max(level, 1)}] {cleaned_title[:80]} | page {page}"
        )

    return toc_lines


def maybe_generate_fallback_toc(
    parser, toc_string: str, markdown_path: Path, filepath: str
) -> str:
    """Generate fallback TOC if Docling produced none."""
    docling_lines = [line for line in toc_string.splitlines() if line.strip()]
    if Path(filepath).suffix.lower() == ".pdf":
        resolved = _resolve_pdf_toc(parser, filepath, docling_lines, toc_string)
        if resolved is not None:
            return resolved

    return _build_fallback_toc(parser, markdown_path)


def _read_markdown(markdown_path: Path) -> str:
    with open(markdown_path, "r", encoding="utf-8") as handle:
        return handle.read()


def _build_fallback_toc_lines(content: str) -> List[str]:
    toc_lines: List[str] = []
    numbered_pattern = _numbered_heading_pattern()
    keyword_patterns = _keyword_patterns()
    page_pattern = re.compile(r"------- Page (\d+) -------")
    current_page = 1
    seen_titles: set[str] = set()

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        page_match = page_pattern.search(line)
        if page_match:
            current_page = int(page_match.group(1))
            continue
        if line.startswith("|") or line.startswith("![") or len(line) < 5:
            continue
        if _handle_numbered_line(
            line, numbered_pattern, current_page, seen_titles, toc_lines
        ):
            continue
        _handle_keyword_line(
            line, keyword_patterns, current_page, seen_titles, toc_lines
        )

    return toc_lines


def _numbered_heading_pattern() -> re.Pattern:
    return re.compile(
        r"^(\d+(?:\.\d+)*)\s*\.?\s+([A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞ]"
        r"[^\n]{3,80})$",
        re.MULTILINE,
    )


def _keyword_patterns() -> List[tuple[str, int]]:
    return [
        (
            r"^(Introduction|Conclusion|Recommendations|Methodology|Results|"
            r"Discussion|Summary|Abstract|Background|Appendix|Annex|"
            r"Bibliography|References|Acknowledgements)$",
            2,
        ),
        (
            r"^(Introduction|Conclusion|Recommandations|Méthodologie|Résultats|"
            r"Résumé|Contexte|Appendice|Annexe|Bibliographie|Références|"
            r"Remerciements)$",
            2,
        ),
        (
            r"^(Introducción|Conclusión|Recomendaciones|Metodología|Resultados|"
            r"Resumen|Contexto|Apéndice|Anexo|Bibliografía|Referencias|"
            r"Agradecimientos)$",
            2,
        ),
    ]


def _handle_numbered_line(
    line: str,
    numbered_pattern: re.Pattern,
    current_page: int,
    seen_titles: set[str],
    toc_lines: List[str],
) -> bool:
    num_match = numbered_pattern.match(line)
    if not num_match:
        return False
    section_num = num_match.group(1)
    title = num_match.group(2).strip()
    full_title = f"{section_num}. {title}"
    level = min(section_num.count(".") + 2, 5)
    if full_title.lower() not in seen_titles:
        seen_titles.add(full_title.lower())
        indent = "  " * (level - 2)
        toc_lines.append(f"{indent}[H{level}] {full_title[:80]} | page {current_page}")
    return True


def _handle_keyword_line(
    line: str,
    keyword_patterns: List[tuple[str, int]],
    current_page: int,
    seen_titles: set[str],
    toc_lines: List[str],
) -> None:
    for pattern, level in keyword_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            if line.lower() not in seen_titles:
                seen_titles.add(line.lower())
                indent = "  " * (level - 2)
                toc_lines.append(
                    f"{indent}[H{level}] {line[:80]} | page {current_page}"
                )
            break


def _should_use_pymupdf_toc(docling_lines: List[str], pymupdf_lines: List[str]) -> bool:
    return (
        bool(docling_lines)
        and bool(pymupdf_lines)
        and len(docling_lines) >= 80
        and len(pymupdf_lines) >= 5
    )


def _docling_toc_is_usable(docling_lines: List[str], toc_string: str) -> bool:
    if not docling_lines:
        return False
    if _is_docling_toc_low_quality(toc_string):
        return False
    if len(docling_lines) < 5:
        return False
    unknown_pages = sum(1 for line in docling_lines if "| page ?" in line)
    return unknown_pages == 0 or unknown_pages / len(docling_lines) <= 0.6


def _resolve_pdf_toc(
    parser, filepath: str, docling_lines: List[str], toc_string: str
) -> str | None:
    pymupdf_lines = generate_pymupdf_toc(parser, filepath)
    if _should_use_pymupdf_toc(docling_lines, pymupdf_lines):
        logger.info(
            "  ⚠ Docling TOC is very large (%s). Using PyMuPDF TOC (%s).",
            len(docling_lines),
            len(pymupdf_lines),
        )
        return "\n".join(pymupdf_lines)
    if _docling_toc_is_usable(docling_lines, toc_string):
        return toc_string
    if pymupdf_lines:
        logger.info(
            "  ⚠ Docling TOC looks empty or low-quality. Using PyMuPDF TOC (%s).",
            len(pymupdf_lines),
        )
        return "\n".join(pymupdf_lines)
    return None


def _build_fallback_toc(parser, markdown_path: Path) -> str:
    logger.info("  ⚠ No section headers detected by Docling, using fallback TOC...")
    fallback_lines = generate_fallback_toc(parser, markdown_path)
    if fallback_lines:
        toc_string = "\n".join(fallback_lines)
        logger.info("  ✓ Generated fallback TOC with %s headings", len(fallback_lines))
        return toc_string

    logger.warning("  ⚠ Fallback TOC also found no headings")
    return ""
