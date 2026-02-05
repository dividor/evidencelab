"""TOC helpers for parsing."""

import logging
from pathlib import Path

from pipeline.processors.parsing.toc_docling import generate_toc_from_docling
from pipeline.processors.parsing.toc_fallback import (
    generate_fallback_toc,
    generate_pymupdf_toc,
    maybe_generate_fallback_toc,
)
from pipeline.processors.parsing.toc_normalize import normalize_toc_mixed_levels
from pipeline.processors.parsing.toc_roman import (
    annotate_toc_with_front_matter,
    annotate_toc_with_roman,
    detect_roman_page_labels,
)

logger = logging.getLogger(__name__)


def write_toc_to_file(_parser, toc_string: str, output_folder: str) -> None:
    """Write TOC string to toc.txt file, cleaning comparison markers if present."""
    cleaned_toc = "\n".join(
        line[2:] if line.startswith("x ") else line for line in toc_string.splitlines()
    )

    toc_path = Path(output_folder) / "toc.txt"
    with open(toc_path, "w", encoding="utf-8") as handle:
        handle.write(cleaned_toc)
    logger.info("  ✓ Wrote TOC to %s", toc_path)


__all__ = [
    "annotate_toc_with_front_matter",
    "annotate_toc_with_roman",
    "detect_roman_page_labels",
    "generate_fallback_toc",
    "generate_pymupdf_toc",
    "generate_toc_from_docling",
    "maybe_generate_fallback_toc",
    "normalize_toc_mixed_levels",
    "write_toc_to_file",
]
