"""Core parsing workflow helpers."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_document_internal(
    parser, filepath: str, output_folder: str, doc_id: str | None = None
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], str, str]:
    """
    Parse document using Docling.

    Returns:
        Tuple of (markdown_path, toc_string, page_count, word_count, language, file_format)
    """
    file_ext = Path(filepath).suffix.lower()
    file_format = file_ext[1:] if file_ext else "unknown"
    language = parser._detect_language(filepath)

    superscripts: Dict[int, List[Tuple[str, str]]] = {}
    if parser.enable_superscripts:
        superscripts = parser._detect_superscripts_via_geometry(filepath)
        parser._log_superscript_detection(superscripts, filepath)
    else:
        logger.debug("DEBUG: enable_superscripts is False")

    page_count = parser._get_pdf_page_count(filepath, file_format)

    logger.info("  Converting document...")
    assert parser._converter is not None
    result = parser._converter.convert(source=filepath)
    logger.info("  ✓ Conversion complete")

    logger.info("  Applying hierarchical postprocessor...")
    parser._apply_hierarchical_postprocessor(result, filepath)

    hierarchy_exists = parser._check_if_hierarchy_exists(result)
    toc_fix_result = None
    if not hierarchy_exists:
        logger.info("  No heading hierarchy detected. Trying hybrid approach...")
        parser._apply_hybrid_heading_detection(result, Path(filepath))
    else:
        logger.debug(
            "  Heading hierarchy exists, skipping hybrid detection and TOC fix"
        )

    docling_toc = parser._generate_toc_from_docling(result)

    toc_string = docling_toc

    pdf_filename = Path(filepath).stem
    markdown_path = parser._save_markdown_artifacts(result, output_folder, pdf_filename)

    if parser.enable_superscripts and superscripts:
        try:
            parser._apply_superscripts_to_markdown(markdown_path, superscripts)
        except Exception as exc:
            logger.warning("  ⚠ Failed to apply superscripts: %s", exc)
        parser._apply_superscripts_to_docling_items(result.document, superscripts)

    toc_string, word_count = parser._finalize_parsing_outputs(
        result,
        output_folder,
        filepath,
        markdown_path,
        toc_string,
        toc_fix_result,
        page_count,
    )

    logger.info("  ✓ Parsed: %s pages, %s words", page_count or "?", word_count)

    return (
        str(markdown_path),
        toc_string,
        page_count,
        word_count,
        language,
        file_format,
    )
