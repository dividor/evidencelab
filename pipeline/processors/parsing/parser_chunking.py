"""Chunking helpers for ParseProcessor."""

import logging
import re
import signal
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from docling_core.types.doc import DoclingDocument, ImageRefMode
from hierarchical.postprocessor import ResultPostprocessor

from pipeline.processors.parsing.parser_constants import PAGE_SEPARATOR

logger = logging.getLogger(__name__)


def _apply_alarm(parser, is_main_thread: bool) -> None:
    if not is_main_thread:
        return
    signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))
    signal.alarm(parser.chunk_timeout)


def _clear_alarm(is_main_thread: bool) -> None:
    if is_main_thread:
        signal.alarm(0)


def _parse_chunk_with_timeout(
    parser, chunk_info: dict, is_main_thread: bool
) -> Dict[str, Any]:
    try:
        _apply_alarm(parser, is_main_thread)
        return parse_chunk(
            parser,
            chunk_info["path"],
            chunk_info["chunk_num"],
            chunk_info["start_page"],
        )
    except TimeoutError:
        logger.error(
            "  ✗ Chunk timeout for pages %s-%s",
            chunk_info["start_page"],
            chunk_info["end_page"],
        )
        return {"success": False, "error": "Timeout"}
    except Exception as exc:
        logger.error("  ✗ Chunk error: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        _clear_alarm(is_main_thread)


def parse_chunks(parser, chunk_files: list[dict]) -> list[dict]:
    """Parse PDF chunks with optional timeouts."""
    chunk_results = []
    is_main_thread = threading.current_thread() is threading.main_thread()

    for i, chunk_info in enumerate(chunk_files, 1):
        logger.info(
            "  Chunk %s/%s: pages %s-%s",
            i,
            len(chunk_files),
            chunk_info["start_page"],
            chunk_info["end_page"],
        )
        chunk_results.append(
            _parse_chunk_with_timeout(parser, chunk_info, is_main_thread)
        )

    return chunk_results


def parse_with_chunking(
    parser, filepath: str, output_folder: str
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], str, str]:
    """Parse large PDF using chunking for memory efficiency."""
    logger.info("  Using chunked parsing (memory-efficient mode)")

    file_format = "pdf"
    language = parser._detect_language(filepath)

    chunk_files, temp_dir = split_pdf(parser, filepath)

    try:
        chunk_results = parse_chunks(parser, chunk_files)

        successful_chunks = sum(1 for result in chunk_results if result.get("success"))
        if successful_chunks == 0:
            logger.error(
                "  ✗ All %s chunks failed - marking as parse failure",
                len(chunk_results),
            )
            return (None, None, None, None, language, file_format)

        pdf_filename = Path(filepath).stem
        markdown_path, toc_string = merge_chunks(
            parser, chunk_results, output_folder, pdf_filename, chunk_files
        )

        total_pages = sum(c["end_page"] - c["start_page"] + 1 for c in chunk_files)
        word_count = (
            parser._count_words(Path(markdown_path))
            if markdown_path and Path(markdown_path).exists()
            else 0
        )

        parser._create_symlink(filepath, output_folder)

        return (
            markdown_path,
            toc_string,
            total_pages,
            word_count,
            language,
            file_format,
        )
    finally:
        cleanup_chunks(chunk_files, temp_dir)


def split_pdf(parser, filepath: str) -> Tuple[list, str]:
    """Split PDF into chunks."""
    temp_dir = tempfile.mkdtemp(prefix="pdf_chunks_")
    doc = fitz.open(str(filepath))
    total_pages = len(doc)

    chunk_files = []
    chunk_num = 0

    for start_page in range(0, total_pages, parser.chunk_size):
        end_page = min(start_page + parser.chunk_size, total_pages)
        chunk_num += 1

        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)

        chunk_path = Path(temp_dir) / f"{Path(filepath).stem}_chunk_{chunk_num:03d}.pdf"
        chunk_doc.save(str(chunk_path))
        chunk_doc.close()

        chunk_files.append(
            {
                "path": str(chunk_path),
                "chunk_num": chunk_num,
                "start_page": start_page + 1,
                "end_page": end_page,
            }
        )
    doc.close()
    logger.info("  Split into %s chunks", len(chunk_files))
    return chunk_files, temp_dir


def parse_chunk(parser, chunk_path: str, _chunk_num: int, start_page: int) -> Dict:
    """Parse a single PDF chunk."""
    try:
        result = parser._converter.convert(  # type: ignore[attr-defined]
            source=chunk_path
        )

        chunk_superscripts = {}
        if parser.enable_superscripts:
            chunk_superscripts = parser._detect_superscripts_via_geometry(chunk_path)

        if ResultPostprocessor is not None:
            ResultPostprocessor(result, source=chunk_path).process()
        else:
            logger.warning(
                "ResultPostprocessor not available, skipping hierarchical processing for chunk"
            )

        parser._apply_hybrid_heading_detection(result, Path(chunk_path))

        toc_lines = _build_chunk_toc(result, start_page)

        return {
            "result": result,
            "toc": "\n".join(toc_lines),
            "success": True,
            "superscripts": chunk_superscripts,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "toc": "", "superscripts": {}}


def _get_heading_level(item: Any) -> str | int:
    raw_level = getattr(item, "level", -1)
    return raw_level + 1 if raw_level != -1 else "?"


def _get_heading_page(item: Any, start_page: int) -> str | int:
    if hasattr(item, "prov") and item.prov:
        for prov_item in item.prov:
            if hasattr(prov_item, "page_no"):
                return start_page + prov_item.page_no - 1
    return "?"


def _build_chunk_toc(result: Any, start_page: int) -> List[str]:
    toc_lines = []
    for item, level in result.document.iterate_items():
        if hasattr(item, "text") and type(item).__name__ == "SectionHeaderItem":
            indent = "  " * level
            heading_level = _get_heading_level(item)
            page_num = _get_heading_page(item, start_page)
            toc_lines.append(
                f"{indent}[H{heading_level}] {item.text[:80]} | page {page_num}"
            )
    return toc_lines


def merge_chunks(
    parser,
    chunk_results: list,
    output_folder: str,
    pdf_filename: str,
    chunk_files: list,
) -> Tuple[str, str]:
    """Merge parsed chunk results including JSON for indexer."""
    markdown_path = Path(output_folder) / f"{pdf_filename}.md"
    json_path = Path(output_folder) / f"{pdf_filename}.json"
    images_dir = Path(output_folder).resolve() / "images"
    images_dir.mkdir(exist_ok=True, parents=True)

    chunk_documents: List[DoclingDocument] = []

    with open(markdown_path, "w", encoding="utf-8") as outfile:
        for i, chunk_result in enumerate(chunk_results):
            chunk_info = chunk_files[i]
            start_page = chunk_info["start_page"]

            if not chunk_result["success"]:
                outfile.write(
                    f"\n<!-- CHUNK {i+1} FAILED: {chunk_result.get('error')} -->\n"
                )
                continue

            result = chunk_result["result"]
            _update_footnote_prefixes(parser, result)

            chunk_md = Path(output_folder) / f"_chunk_{i}_temp.md"
            result.document.save_as_markdown(
                filename=chunk_md,
                artifacts_dir=images_dir,
                image_mode=ImageRefMode.REFERENCED,
                page_break_placeholder=PAGE_SEPARATOR.strip(),
            )

            parts = []
            if chunk_md.exists():
                with open(chunk_md, "r", encoding="utf-8") as handle:
                    content = handle.read()
                chunk_md.unlink()

                if parser.enable_superscripts:
                    superscripts = chunk_result.get("superscripts", {})
                    if superscripts:
                        content = _apply_superscripts_to_content(
                            parser, result, content, superscripts
                        )

                parts = content.split(PAGE_SEPARATOR.strip())

            if not parts:
                continue

            _write_chunk_parts(outfile, parts, start_page, i)

            chunk_documents.append(result.document)

    merged_doc = None
    if chunk_documents:
        try:
            if len(chunk_documents) == 1:
                merged_doc = chunk_documents[0]
            else:
                merged_doc = DoclingDocument.concatenate(chunk_documents)
            merged_doc.save_as_json(json_path)
            logger.info("  ✓ Saved merged JSON from %s chunks", len(chunk_documents))
        except Exception as exc:
            logger.warning("  ⚠ Could not merge JSON: %s", exc)

    toc_lines = [result.get("toc", "") for result in chunk_results if result.get("toc")]
    merged_toc = "\n".join(toc_lines)

    toc_path = Path(output_folder) / "toc.txt"
    with open(toc_path, "w", encoding="utf-8") as handle:
        handle.write(merged_toc)

    return str(markdown_path), merged_toc


def _update_footnote_prefixes(parser, result: Any) -> None:
    for item, _ in result.document.iterate_items():
        label = str(getattr(item, "label", "")).lower()
        if "footnote" not in label:
            continue
        match = re.match(r"^(\s*)(\d+)\b", item.text)
        if not match:
            continue
        prefix_ws = match.group(1)
        number = match.group(2)
        if parser.superscript_mode == "caret":
            if not item.text.lstrip().startswith("^"):
                new_start = f"{prefix_ws}^{number}"
                item.text = new_start + item.text[match.end() :]
        else:
            if "<sup>" not in item.text:
                new_start = f"{prefix_ws}<sup>{number}</sup>"
                item.text = new_start + item.text[match.end() :]


def _apply_superscripts_to_content(
    parser, result: Any, content: str, superscripts: Dict[int, List[Tuple[str, str]]]
) -> str:
    replacement_template = (
        "<sup>{}</sup>" if parser.superscript_mode == "html" else "^{}"
    )
    all_rules = []
    for page_rules in superscripts.values():
        all_rules.extend(page_rules)
    content = _apply_superscript_rules(content, all_rules, replacement_template)
    _apply_superscripts_to_document(result, all_rules, replacement_template)
    return content


def _apply_superscript_rules(
    content: str, all_rules: List[Tuple[str, str]], replacement_template: str
) -> str:
    for regex_pattern, token in all_rules:
        try:
            annotated_token = replacement_template.format(token)

            def replace_func(match, repl=annotated_token):
                return match.group(0).replace(match.group(1), repl, 1)

            content = re.sub(regex_pattern, replace_func, content)
        except re.error:
            pass
    return content


def _apply_superscripts_to_document(
    result: Any, all_rules: List[Tuple[str, str]], replacement_template: str
) -> None:
    spaced_text_pattern = r"\b(?:[a-zA-Z]\s+){3,}[a-zA-Z]\b"
    for item, _ in result.document.iterate_items():
        if not (hasattr(item, "text") and item.text):
            continue
        original_text = item.text
        modified_text = _apply_superscript_rules(
            original_text, all_rules, replacement_template
        )
        if re.search(spaced_text_pattern, modified_text):
            modified_text = re.sub(
                spaced_text_pattern,
                lambda match: match.group(0).replace(" ", ""),
                modified_text,
            )
        if modified_text != original_text:
            item.text = modified_text


def _write_chunk_parts(
    outfile, parts: List[str], start_page: int, chunk_index: int
) -> None:
    if chunk_index > 0:
        outfile.write(f"\n\n------- Page {start_page} -------\n\n")
    outfile.write(parts[0])
    for j, part in enumerate(parts[1:], 1):
        outfile.write(f"\n\n------- Page {start_page + j} -------\n\n")
        outfile.write(part)


def cleanup_chunks(chunk_files: list, temp_dir: str) -> None:
    """Clean up temporary chunk files."""
    for chunk_info in chunk_files:
        try:
            Path(chunk_info["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        Path(temp_dir).rmdir()
    except Exception:
        pass
