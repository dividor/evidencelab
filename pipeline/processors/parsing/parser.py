"""
parser.py - Document parsing processor using Docling.

This processor handles PDF, DOCX, and DOC file parsing with:
- Structured text extraction (markdown)
- Table of contents generation with hierarchical headings
- Document language detection
- Page count and word count statistics
- Automatic chunking for large documents
- OOM protection through subprocess isolation
- Automatic conversion of DOC/DOCX to PDF for consistent viewing
"""

import logging
import multiprocessing
import os
import platform
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import torch
from docling.backend.docling_parse_v2_backend import DoclingParseV2DocumentBackend
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    TableFormerMode,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling_core.types.doc import DoclingDocument, ImageRefMode
from langdetect import detect_langs

from pipeline.processors.base import BaseProcessor
from pipeline.processors.parsing.parser_chunking import (
    cleanup_chunks,
    merge_chunks,
    parse_chunk,
    parse_chunks,
    parse_with_chunking,
    split_pdf,
)
from pipeline.processors.parsing.parser_constants import (
    DATA_PATH_PREFIX,
    DEFAULT_DATA_MOUNT_PATH,
    PAGE_SEPARATOR,
)
from pipeline.processors.parsing.parser_core import parse_document_internal
from pipeline.processors.parsing.parser_headings import (
    apply_hierarchical_postprocessor,
    apply_hybrid_heading_detection,
    check_if_hierarchy_exists,
    extract_hybrid_headings,
    get_top_level_sections,
    infer_level_from_numbering,
)
from pipeline.processors.parsing.parser_images import (
    fix_picture_captions,
    make_relative_path,
    save_images_metadata,
    save_table_images,
)
from pipeline.processors.parsing.parser_superscripts import (
    apply_superscripts_to_docling_items,
    apply_superscripts_to_markdown,
    detect_superscripts_via_geometry,
    flatten_superscripts,
    log_superscript_detection,
)
from pipeline.processors.parsing.parser_toc import (
    annotate_toc_with_front_matter,
    annotate_toc_with_roman,
    detect_roman_page_labels,
    generate_fallback_toc,
    generate_toc_from_docling,
    maybe_generate_fallback_toc,
    normalize_toc_mixed_levels,
    write_toc_to_file,
)
from pipeline.utilities.text_cleaning import clean_text

logger = logging.getLogger(__name__)


def _parse_pdf_worker(filepath, output_folder, parser_config, result_queue):
    """Worker function to parse document in a separate process (OOM protection)."""
    try:
        parser = ParseProcessor(**parser_config)
        parser._init_converter()
        result = parser._parse_document_internal(filepath, output_folder, doc_id=None)
        result_queue.put({"success": True, "result": result})
    except Exception as e:
        result_queue.put(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()}
        )


class ParseProcessor(BaseProcessor):
    """
    Document parsing processor using Docling.

    Handles PDF, DOCX, and DOC files with:
    - Structured text extraction to markdown
    - Hierarchical TOC generation
    - Language detection
    - Automatic chunking for large PDFs
    - OOM-safe subprocess isolation
    """

    name = "ParseProcessor"
    stage_name = "parse"

    def __init__(
        self,
        output_dir: str = "./data/parsed",
        table_mode: str = "fast",
        no_ocr: bool = True,
        images_scale: float = 1.0,
        enable_chunking: bool = False,  # Disabled: chunked parsing produces different output
        chunk_size: int = 50,
        chunk_threshold: int = 200,
        chunk_timeout: int = 300,
        use_subprocess: (
            bool | None
        ) = None,  # Controlled by PARSE_USE_SUBPROCESS env var
        subprocess_timeout: int = 1200,  # 20 minute timeout per document
        _chunk_overlap: int = 0,
        enable_superscripts: bool = True,
        superscript_mode: str = "caret",  # "html" or "caret"
    ):
        """
        Initialize parser configuration.

        Args:
            output_dir: Directory for parsed output files
            table_mode: Table extraction mode ('fast' or 'accurate')
            no_ocr: If True, disable OCR for faster processing
            images_scale: Image resolution scale (1.0 = normal)
            enable_chunking: Enable automatic chunking for large PDFs
            chunk_size: Number of pages per chunk
            chunk_threshold: Minimum pages to trigger chunking
            chunk_timeout: Timeout per chunk in seconds
            use_subprocess: Run parsing in subprocess for OOM protection.
                If None, reads from PARSE_USE_SUBPROCESS env var (default: false).
                Set to false when running in Docker/containers (Docker provides isolation).
            subprocess_timeout: Timeout for subprocess parsing (seconds)
        """
        super().__init__()
        self.output_dir = output_dir
        self.table_mode = table_mode
        self.no_ocr = no_ocr
        self.images_scale = images_scale
        self.enable_chunking = enable_chunking
        self.chunk_size = chunk_size
        self.chunk_threshold = chunk_threshold
        self.chunk_timeout = chunk_timeout
        # Default to false - Docker/containers provide isolation
        # Set PARSE_USE_SUBPROCESS=true for local dev without Docker
        if use_subprocess is None:
            self.use_subprocess = (
                os.getenv("PARSE_USE_SUBPROCESS", "false").lower() == "true"
            )
        else:
            self.use_subprocess = use_subprocess
        self.subprocess_timeout = subprocess_timeout
        self.enable_superscripts = enable_superscripts
        self.superscript_mode = superscript_mode
        self._converter = None

    def _init_converter(self) -> None:
        """Initialize the Docling document converter with GPU acceleration."""
        # Configure GPU acceleration (AUTO will use CUDA if available)
        accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.AUTO,
        )

        # Use ThreadedPdfPipelineOptions for better batch processing
        # Higher batch sizes improve GPU utilization significantly
        pipeline_options = ThreadedPdfPipelineOptions(
            do_ocr=not self.no_ocr,
            do_table_structure=True,
            table_structure_options=TableStructureOptions(
                mode=(
                    TableFormerMode.FAST
                    if self.table_mode == "fast"
                    else TableFormerMode.ACCURATE
                )
            ),
            images_scale=self.images_scale,
            generate_page_images=False,
            generate_picture_images=True,
            generate_table_images=True,
            # Batch sizes for GPU acceleration (Reduced for stability)
            ocr_batch_size=8,
            layout_batch_size=8,
            table_batch_size=4,
            accelerator_options=accelerator_options,
        )

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=StandardPdfPipeline,
                    pipeline_options=pipeline_options,
                    backend=DoclingParseV2DocumentBackend,
                ),
                InputFormat.DOCX: None,
            }
        )

    def setup(self) -> None:
        """Load Docling models (slow - done once)."""
        logger.info("Initializing %s...", self.name)
        logger.info("Loading Docling models (this may take a minute on first run)...")

        os.makedirs(self.output_dir, exist_ok=True)
        self._init_converter()

        logger.info("✓ Docling converter initialized")
        super().setup()

    def _detect_file_type(self, filepath: str) -> str:
        """
        Detect actual file type using magic bytes.

        Returns: 'pdf', 'docx', 'doc', or 'unknown'
        """
        try:
            with open(filepath, "rb") as f:
                header = f.read(8)

            # PDF: starts with %PDF
            if header.startswith(b"%PDF"):
                return "pdf"

            # DOCX/XLSX/PPTX (Office Open XML): starts with PK (ZIP)
            if header.startswith(b"PK\x03\x04"):
                return "docx"

            # DOC (OLE2): starts with D0 CF 11 E0
            if header.startswith(b"\xd0\xcf\x11\xe0"):
                return "doc"

            return "unknown"
        except Exception:
            return "unknown"

    def _convert_to_pdf(self, filepath: str) -> Optional[str]:
        """
        Convert DOC/DOCX file to PDF using LibreOffice.

        Args:
            filepath: Path to the DOC/DOCX file

        Returns:
            Path to converted PDF, or None if conversion failed
        """
        try:
            # Create temp directory for conversion
            temp_dir = tempfile.mkdtemp(prefix="doc_convert_")

            # Run LibreOffice headless conversion
            cmd = [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                temp_dir,
                filepath,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,  # 4 minute timeout for conversion
            )

            if result.returncode != 0:
                logger.error("LibreOffice conversion failed: %s", result.stderr)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None

            # Find the converted PDF
            stem = Path(filepath).stem
            converted_pdf = Path(temp_dir) / f"{stem}.pdf"

            if not converted_pdf.exists():
                logger.error("Converted PDF not found at %s", converted_pdf)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None

            # Move converted PDF to same directory as original, with .pdf extension
            original_path = Path(filepath)
            target_pdf = original_path.parent / f"{stem}.pdf"

            # If original was named .pdf but was actually DOCX, rename it first
            if original_path.suffix.lower() == ".pdf":
                actual_ext = self._detect_file_type(filepath)
                backup_path = original_path.parent / f"{stem}.{actual_ext}"
                shutil.move(str(original_path), str(backup_path))
                logger.info("  Renamed mislabeled file to: %s", backup_path.name)

            # Move converted PDF to target location
            shutil.move(str(converted_pdf), str(target_pdf))
            shutil.rmtree(temp_dir, ignore_errors=True)

            logger.info("  ✓ Converted to PDF: %s", target_pdf.name)
            return str(target_pdf)

        except subprocess.TimeoutExpired:
            logger.error("LibreOffice conversion timed out for %s", filepath)
            return None
        except Exception as e:
            logger.error("Conversion error: %s", e)
            return None

    def _convert_doc_to_docx_mac(self, filepath: str) -> Optional[str]:
        """
        Convert .doc to .docx using macOS native textutil.

        Args:
            filepath: Path to the .doc file

        Returns:
            Path to converted .docx file, or None if failed
        """
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp(prefix="doc_convert_mac_")

            filename = Path(filepath).stem
            output_docx = Path(temp_dir) / f"{filename}.docx"

            cmd = [
                "textutil",
                "-convert",
                "docx",
                filepath,
                "-output",
                str(output_docx),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("textutil conversion failed: %s", result.stderr)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None

            if not output_docx.exists():
                logger.error("Converted DOCX not found at %s", output_docx)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None

            # Move to target location (same dir as original)
            original_path = Path(filepath)
            target_docx = original_path.parent / f"{filename}.docx"

            shutil.move(str(output_docx), str(target_docx))
            shutil.rmtree(temp_dir, ignore_errors=True)

            logger.info(
                "  ✓ Converted .doc to .docx (via textutil): %s", target_docx.name
            )
            return str(target_docx)

        except Exception as e:
            logger.error("textutil error: %s", e)
            return None

    def _ensure_supported_format(self, filepath: str, title: str) -> Tuple[str, bool]:
        """
        Ensure file is in a supported format (PDF or DOCX), converting if necessary.

        Strategies:
        1. macOS + .doc: Convert to .docx using textutil (Fast, Native)
        2. Linux + .doc: Convert to .pdf using soffice (Robust, Isolated)
        3. DOCX/PDF: Use as-is

        Args:
            filepath: Path to the file
            title: Document title for logging

        Returns:
            Tuple of (filepath to use, was_converted)
        """
        actual_type = self._detect_file_type(filepath)

        # If it's already PDF or DOCX, use as-is
        if actual_type in ("pdf", "docx"):
            return filepath, False

        # If it's a legacy .doc file
        if actual_type == "doc":
            is_mac = platform.system() == "Darwin"

            if is_mac:
                # macOS Strategy: .doc -> .docx (textutil)
                logger.info(
                    "  Detected legacy DOC file on macOS. Using textutil to convert to DOCX..."
                )
                converted = self._convert_doc_to_docx_mac(filepath)
                if converted:
                    return converted, True

            # Linux Strategy (or Mac Fallback): .doc -> .pdf (soffice)
            logger.info(
                "  Detected %s file, converting to PDF via LibreOffice...",
                actual_type.upper(),
            )
            converted = self._convert_to_pdf(filepath)
            if converted:
                return converted, True
            else:
                logger.warning("  ⚠ Conversion failed, attempting to parse as-is")
                return filepath, False

        # Unknown type - try to parse as-is
        return filepath, False

    def _resolve_data_filepath(self, filepath: str) -> str:
        """Resolve stored data paths using DATA_MOUNT_PATH."""
        data_mount_path = os.getenv("DATA_MOUNT_PATH", DEFAULT_DATA_MOUNT_PATH)
        if filepath.startswith(DATA_PATH_PREFIX):
            return os.path.join(data_mount_path, filepath[len(DATA_PATH_PREFIX) :])
        return filepath

    def _build_parse_failure(
        self,
        doc: Dict[str, Any],
        error_message: str,
        error_detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a failed parse response with stage updates."""
        stage_updates = self.build_stage_updates(
            doc, success=False, error=error_message
        )
        detail = error_detail or error_message
        return {
            "success": False,
            "updates": {
                "sys_status": "parse_failed",
                "sys_error_message": error_message,
                **stage_updates,
            },
            "error": detail,
        }

    def _should_use_subprocess(self) -> bool:
        """Determine whether to use subprocess isolation for parsing."""
        if not self.use_subprocess:
            return False
        if torch.cuda.is_initialized():
            logger.info("  CUDA detected - skipping subprocess isolation")
            return False
        return True

    def process_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a single document.

        Args:
            doc: Document dict with 'id', 'filepath', 'title' fields

        Returns:
            Dict with success status and updates for database
        """
        self.ensure_setup()

        filepath = doc.get("sys_filepath")
        title = doc.get("map_title", "Unknown")
        doc_id = doc.get("id")

        # Store doc_id for use in _parse_document_internal
        self._current_doc_id = doc_id

        if not filepath:
            return self._build_parse_failure(doc, "No filepath")

        # Resolve relative paths using DATA_MOUNT_PATH
        # Paths are stored as relative (data/uneg/...) but need to resolve to actual location
        filepath = self._resolve_data_filepath(filepath)

        if not os.path.exists(filepath):
            return self._build_parse_failure(
                doc, "File not found", error_detail=f"File not found: {filepath}"
            )

        # Convert DOC/DOCX to PDF (Linux) or proper DOCX (Mac) if needed
        original_filepath = filepath
        filepath, was_converted = self._ensure_supported_format(filepath, title)

        # Get file size early for error reporting
        file_size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 2)

        logger.info(
            "Parsing: %s\n  File: %s (%.2f MB)",
            title,
            os.path.abspath(filepath),
            file_size_mb,
        )

        # Create output folder (use original filepath for folder structure)
        output_folder = self._create_output_folder(original_filepath)

        # Use subprocess isolation for OOM protection
        # But skip if CUDA is initialized (can't fork with CUDA)
        if self._should_use_subprocess():
            result = self._parse_in_subprocess(
                filepath, output_folder, title, file_size_mb
            )
        else:
            result = self._parse_direct(filepath, output_folder, title, file_size_mb)

        # If file was converted, update the filepath in the result
        if was_converted and result.get("success"):
            result["updates"]["sys_filepath"] = filepath
            result["updates"]["sys_converted_from"] = original_filepath

        # Add stage tracking to result
        if result.get("success"):
            stage_updates = self.build_stage_updates(
                doc,
                success=True,
                page_count=result["updates"].get("page_count"),
                word_count=result["updates"].get("word_count"),
            )
        else:
            stage_updates = self.build_stage_updates(
                doc,
                success=False,
                error=result.get("error") or result["updates"].get("error_message"),
            )
        result["updates"].update(stage_updates)

        return result

    def _parse_in_subprocess(
        self, filepath: str, output_folder: str, title: str, file_size_mb: float
    ) -> Dict[str, Any]:
        """Parse document in subprocess for OOM protection."""
        result_queue: multiprocessing.Queue = multiprocessing.Queue()  # type: ignore

        # Config to recreate parser in subprocess
        parser_config = {
            "output_dir": self.output_dir,
            "table_mode": self.table_mode,
            "no_ocr": self.no_ocr,
            "images_scale": self.images_scale,
            "enable_chunking": self.enable_chunking,
            "chunk_size": self.chunk_size,
            "chunk_threshold": self.chunk_threshold,
            "chunk_timeout": self.chunk_timeout,
            "use_subprocess": False,  # Don't nest subprocesses
            "enable_superscripts": self.enable_superscripts,
            "superscript_mode": self.superscript_mode,
        }

        process = multiprocessing.Process(
            target=_parse_pdf_worker,
            args=(filepath, output_folder, parser_config, result_queue),
        )
        process.start()
        process.join(timeout=self.subprocess_timeout)

        if process.is_alive():
            # Timeout - kill the process
            logger.error(
                "TIMEOUT parsing %s: exceeded %ss", title, self.subprocess_timeout
            )
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
            error_msg = (
                f"Timeout after {self.subprocess_timeout}s ({file_size_mb}MB file)"
            )
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": error_msg,
                },
                "error": "Subprocess timeout",
            }

        # Check exit code - negative means killed by signal (e.g., OOM killer sends SIGKILL=-9)
        exit_code = process.exitcode
        if exit_code is None or exit_code < 0:
            signal_num = -exit_code if exit_code else 0
            signal_name = "SIGKILL (OOM)" if signal_num == 9 else f"signal {signal_num}"
            logger.error("SUBPROCESS KILLED parsing %s: %s", title, signal_name)
            logger.error("  File size: %s MB - likely out of memory", file_size_mb)
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": f"Process killed ({signal_name}): {file_size_mb}MB file likely too large",  # noqa: E501
                },
                "error": f"Subprocess killed by {signal_name}",
            }

        # Get result from queue
        try:
            worker_result = result_queue.get_nowait()
        except Exception:
            logger.error("No result from subprocess parsing %s", title)
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": "No result from subprocess",
                },
                "error": "Subprocess returned no result",
            }

        if not worker_result.get("success"):
            error_msg = worker_result.get("error", "Unknown error")
            logger.error("Subprocess error parsing %s: %s", title, error_msg)
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": error_msg,
                },
                "error": error_msg,
            }

        # Extract result tuple from worker
        result = worker_result["result"]
        if result[0]:  # markdown_path exists
            markdown_path, toc, pages, words, lang, fmt = result
            return {
                "success": True,
                "updates": {
                    "sys_status": "parsed",
                    "sys_parsed_folder": self._make_relative_path(str(output_folder)),
                    "sys_toc": toc or "",
                    "sys_language": lang or "Unknown",
                    "sys_page_count": pages,
                    "sys_word_count": words,
                    "sys_file_format": fmt,
                    "sys_file_size_mb": file_size_mb,
                },
                "error": None,
            }
        else:
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": "Parsing returned None",
                },
                "error": "Parsing failed",
            }

    def _parse_direct(
        self, filepath: str, output_folder: str, title: str, file_size_mb: float
    ) -> Dict[str, Any]:
        """Parse document directly (no subprocess isolation)."""
        try:
            # Parse with chunking if needed
            # Get doc_id from the doc dict if available
            doc_id = getattr(self, "_current_doc_id", None)
            if self.enable_chunking and self._should_chunk(filepath):
                result = self._parse_with_chunking(filepath, output_folder)
            else:
                result = self._parse_document_internal(
                    filepath, output_folder, doc_id=doc_id
                )

            if result[0]:  # markdown_path exists
                markdown_path, toc, pages, words, lang, fmt = result
                return {
                    "success": True,
                    "updates": {
                        "sys_status": "parsed",
                        "sys_parsed_folder": self._make_relative_path(
                            str(output_folder)
                        ),
                        "sys_toc": toc or "",
                        "sys_language": lang or "Unknown",
                        "sys_page_count": pages,
                        "sys_word_count": words,
                        "sys_file_format": fmt,
                        "sys_file_size_mb": file_size_mb,
                    },
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "updates": {
                        "sys_status": "parse_failed",
                        "sys_error_message": "Parsing returned None",
                    },
                    "error": "Parsing failed",
                }

        except MemoryError as e:
            logger.error(
                "MEMORY ERROR parsing %s: Out of memory. Document may be too large.",
                title,
            )
            logger.error("  File size: %s MB, Path: %s", file_size_mb, filepath)
            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": f"Out of memory: {file_size_mb}MB file too large",
                },
                "error": f"MemoryError: {e}",
            }
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # Check for memory-related errors that don't raise MemoryError
            if "memory" in error_msg.lower() or "killed" in error_msg.lower():
                logger.error("MEMORY-RELATED ERROR parsing %s: %s", title, error_msg)
                logger.error("  File size: %s MB, Path: %s", file_size_mb, filepath)
            else:
                logger.error(
                    "Exception parsing %s (%s): %s", title, error_type, error_msg
                )

            return {
                "success": False,
                "updates": {
                    "sys_status": "parse_failed",
                    "sys_error_message": f"{error_type}: {error_msg}",
                },
                "error": error_msg,
            }

    def _create_output_folder(self, filepath: str) -> str:
        """Create output folder matching PDF structure: agency/year/document_folder."""
        parts = Path(filepath).parts

        try:
            pdfs_idx = parts.index("pdfs")
            agency = parts[pdfs_idx + 1] if len(parts) > pdfs_idx + 1 else "unknown"
            year = parts[pdfs_idx + 2] if len(parts) > pdfs_idx + 2 else "unknown"
            filename = Path(filepath).stem

            output_folder = Path(self.output_dir) / agency / year / filename
            output_folder.mkdir(parents=True, exist_ok=True)
            return str(output_folder)
        except (ValueError, IndexError):
            filename = Path(filepath).stem
            output_folder = Path(self.output_dir) / "other" / filename
            output_folder.mkdir(parents=True, exist_ok=True)
            return str(output_folder)

    def _should_chunk(self, filepath: str) -> bool:
        """Check if PDF should be chunked based on page count."""
        if not filepath.lower().endswith(".pdf"):
            return False
        try:
            doc = fitz.open(filepath)
            page_count = len(doc)
            doc.close()
            should_chunk = page_count >= self.chunk_threshold
            if should_chunk:
                logger.info(
                    "  %s pages >= %s - will use chunking",
                    page_count,
                    self.chunk_threshold,
                )
            return should_chunk
        except Exception:
            return False

    @staticmethod
    def _build_language_sample_ranges(
        total_pages: int,
    ) -> list[tuple[int, int]]:
        """Return page ranges to sample for language detection."""
        if total_pages <= 6:
            return [(0, total_pages)]
        ranges: list[tuple[int, int]] = []
        # Body start: pages 3-12 (skip cover/TOC)
        s = min(3, total_pages - 1)
        ranges.append((s, min(s + 10, total_pages)))
        # Middle
        mid = total_pages // 2
        m_s = max(mid - 4, ranges[-1][1])
        m_e = min(mid + 4, total_pages)
        if m_s < m_e:
            ranges.append((m_s, m_e))
        # End (skip last 2 pages - often references/appendices)
        e_s = max(total_pages - 10, ranges[-1][1])
        e_e = max(total_pages - 2, e_s + 1)
        if e_s < e_e:
            ranges.append((e_s, e_e))
        return ranges

    @staticmethod
    def _extract_section_text(doc, start: int, end: int) -> str:
        """Extract normalised text from a page range, capped at 5000 chars."""
        parts: list[str] = []
        length = 0
        for i in range(start, end):
            page_text = doc[i].get_text()
            if page_text:
                parts.append(page_text)
                length += len(page_text)
            if length > 5000:
                break
        return " ".join(" ".join(parts).split())

    def _detect_language(self, filepath: str) -> str:
        """Detect document language using majority voting across sections.

        Samples text from three sections (beginning, middle, end) and
        detects the language of each independently.  The final language
        is decided by majority vote so that bilingual cover pages or
        appendices cannot override the body language.
        """
        try:
            doc = fitz.open(filepath)
            total_pages = len(doc)
            if total_pages == 0:
                doc.close()
                return "Unknown"

            sample_ranges = self._build_language_sample_ranges(total_pages)
            votes: dict[str, int] = {}
            for start, end in sample_ranges:
                text = self._extract_section_text(doc, start, end)
                if len(text) < 200:
                    continue
                results = detect_langs(text)
                if results and results[0].prob >= 0.4:
                    votes[results[0].lang] = votes.get(results[0].lang, 0) + 1

            doc.close()
            if not votes:
                return "Unknown"
            return max(votes, key=votes.get)
        except Exception:
            return "Unknown"

    def _detect_superscripts_via_geometry(
        self, filepath: str
    ) -> Dict[int, List[Tuple[str, str]]]:
        """
        Detect potential superscript tokens in PDF using geometry (PyMuPDF).
        Returns:
            Dict mapping page_number (1-indexed) to list of (regex_pattern, token) tuples.
        """
        return detect_superscripts_via_geometry(self, filepath)

    def _get_pdf_page_count(self, filepath: str, file_format: str) -> Optional[int]:
        """Return page count for PDFs when possible."""
        if file_format != "pdf":
            return None
        try:
            doc = fitz.open(filepath)
            page_count = len(doc)
            doc.close()
            return page_count
        except Exception:
            return None

    def _log_superscript_detection(
        self, superscripts: Dict[int, List[Tuple[str, str]]], filepath: str
    ) -> None:
        """Log superscript detection diagnostics."""
        log_superscript_detection(superscripts, filepath)

    def _flatten_superscripts(
        self, superscripts: Dict[int, List[Tuple[str, str]]]
    ) -> List[Tuple[str, str]]:
        """Flatten superscripts dict into a list of rules."""
        return flatten_superscripts(superscripts)

    def _choose_toc_string(
        self, docling_toc: str, toc_fix_result: Optional[Dict[str, Any]]
    ) -> str:
        """Select the final TOC string, preferring corrected TOC when available."""
        if toc_fix_result and toc_fix_result.get("status") == "success":
            corrected_toc = toc_fix_result.get("corrected_toc", "")
            if corrected_toc:
                toc_string = "\n".join(
                    line[2:] if line.startswith("x ") else line
                    for line in corrected_toc.splitlines()
                )
                logger.info(
                    "  ✓ Using corrected TOC with %s headings",
                    len(toc_string.splitlines()),
                )
                return toc_string
            logger.info(
                "  ✓ Generated TOC with %s headings (from Docling, fallback)",
                len(docling_toc.splitlines()),
            )
            return docling_toc

        logger.info(
            "  ✓ Generated TOC with %s headings (from Docling)",
            len(docling_toc.splitlines()),
        )
        return docling_toc

    def _save_markdown_artifacts(
        self, result: Any, output_folder: str, pdf_filename: str
    ) -> Path:
        """Save markdown and return its path."""
        markdown_path = Path(output_folder) / f"{pdf_filename}.md"
        images_dir = Path(output_folder).resolve() / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        result.document.save_as_markdown(
            filename=markdown_path,
            artifacts_dir=images_dir,
            image_mode=ImageRefMode.REFERENCED,
            page_break_placeholder=PAGE_SEPARATOR.strip(),
        )
        return markdown_path

    def _apply_superscripts_to_markdown(
        self, markdown_path: Path, superscripts: Dict[int, List[Tuple[str, str]]]
    ) -> None:
        """Apply superscript annotations to markdown."""
        apply_superscripts_to_markdown(self, markdown_path, superscripts)

    def _apply_superscripts_to_docling_items(
        self, document: DoclingDocument, superscripts: Dict[int, List[Tuple[str, str]]]
    ) -> None:
        """Apply superscripts to Docling document items for JSON/chunk validity."""
        apply_superscripts_to_docling_items(self, document, superscripts)

    def _count_words(self, markdown_path: Path) -> int:
        """Count words in a markdown file."""
        with open(markdown_path, "r", encoding="utf-8") as file_handle:
            return len(file_handle.read().split())

    def _maybe_generate_fallback_toc(
        self, toc_string: str, markdown_path: Path, filepath: str
    ) -> str:
        """Generate fallback TOC if Docling produced none."""
        return maybe_generate_fallback_toc(self, toc_string, markdown_path, filepath)

    def _finalize_parsing_outputs(
        self,
        result: Any,
        output_folder: str,
        filepath: str,
        markdown_path: Path,
        toc_string: str,
        toc_fix_result: Optional[Dict[str, Any]],
        page_count: Optional[int],
    ) -> Tuple[str, int]:
        """Finalize parsing artifacts and return toc/word_count."""
        self._clean_markdown_file(markdown_path)

        json_path = Path(output_folder) / f"{markdown_path.stem}.json"
        result.document.save_as_json(json_path)
        self._fix_picture_captions(json_path)

        table_images = self._save_table_images(result.document, output_folder)
        if table_images:
            logger.info("  ✓ Saved %s table images", len(table_images))

        images_metadata = self._save_images_metadata(result.document, output_folder)
        if images_metadata:
            logger.info("  ✓ Saved metadata for %s images", len(images_metadata))

        toc_string = self._maybe_generate_fallback_toc(
            toc_string, markdown_path, filepath
        )
        if Path(filepath).suffix.lower() == ".pdf":
            roman_labels = detect_roman_page_labels(filepath)
            toc_string = annotate_toc_with_roman(toc_string, roman_labels)
            toc_string = annotate_toc_with_front_matter(
                toc_string, roman_labels, page_count
            )
        toc_string = self._normalize_toc_mixed_levels(toc_string)
        if not (toc_fix_result and toc_fix_result.get("status") == "success"):
            self._write_toc_to_file(toc_string, output_folder)

        self._create_symlink(filepath, output_folder)
        word_count = self._count_words(markdown_path)
        return toc_string, word_count

    def _parse_document_internal(
        self, filepath: str, output_folder: str, doc_id: str | None = None
    ) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], str, str]:
        """
        Parse document using Docling.

        Returns:
            Tuple of (markdown_path, toc_string, page_count, word_count, language, file_format)
        """
        return parse_document_internal(self, filepath, output_folder, doc_id)

    def _clean_markdown_file(self, filepath: Path) -> None:
        """Clean markdown text to fix encoding issues (ligatures, etc.)."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            cleaned = clean_text(content)

            if cleaned != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(cleaned)
                logger.info("  ✓ Cleaned text encoding issues in %s", filepath.name)

        except Exception as e:
            logger.warning("  ⚠ Failed to clean markdown file: %s", e)

    def _add_page_numbers_to_breaks(self, markdown_path: Path, document) -> None:
        """Add page numbers to page break placeholders."""
        try:
            with open(markdown_path, "r", encoding="utf-8") as f:
                content = f.read()

            placeholder = PAGE_SEPARATOR.strip()
            parts = content.split(placeholder)

            if len(parts) <= 1:
                return

            result_parts = [parts[0], "\n\n------- Page 1 -------\n\n"]
            for i, part in enumerate(parts[1:], 1):
                result_parts.append(part)
                result_parts.append(f"\n\n------- Page {i + 1} -------\n\n")

            with open(markdown_path, "w", encoding="utf-8") as f:
                f.write("".join(result_parts))
        except Exception:
            pass

    def _create_symlink(self, filepath: str, output_folder: str) -> None:
        """Create symbolic link to original file."""
        try:
            name = Path(filepath).name
            symlink_path = Path(output_folder) / name
            if symlink_path.is_symlink() or symlink_path.exists():
                symlink_path.unlink()
            symlink_path.symlink_to(Path(filepath).resolve())
        except Exception:
            pass

    def _generate_fallback_toc(self, markdown_path: Path) -> List[str]:
        """
        Generate TOC from markdown when Docling detects no section headers.

        Parses markdown looking for numbered section patterns like:
        - "1. Introduction"
        - "1.1 Section Title"
        - "2.3.1 Subsection"

        Also detects common section keywords in multiple languages.

        Args:
            markdown_path: Path to the markdown file

        Returns:
            List of TOC entries in format "[Hx] Title | page N"
        """
        return generate_fallback_toc(self, markdown_path)

    def _make_relative_path(self, path: str) -> str:
        """
        Convert absolute path to relative path starting with 'data/'.

        Finds '/data/' or 'data/' in the path and returns everything from there.

        Args:
            path: Absolute or relative path

        Returns:
            Relative path starting with 'data/'
        """
        return make_relative_path(path)

    def _fix_picture_captions(self, json_path: Path) -> None:
        """
        Post-process parsed JSON to fix picture captions.

        Docling sometimes classifies picture captions as 'section_header' instead of 'caption',
        causing them to be excluded from chunks by HybridChunker. This method:
        1. Finds picture elements with children that are section_headers
        2. If the section_header text starts with GRAPH, TABLE, CHART, DIAGRAM, etc.,
           converts its label to 'caption' and adds it to the picture's captions array

        Args:
            json_path: Path to the parsed JSON file
        """
        fix_picture_captions(json_path)

    def _save_table_images(self, document, output_folder: str) -> dict:
        """
        Save table images from parsed document.

        Args:
            document: Docling document with parsed tables
            output_folder: Base output folder for parsed content

        Returns:
            Dict mapping table index to image path
        """
        return save_table_images(self, document, output_folder)

    def _apply_hierarchical_postprocessor(self, result: Any, filepath: Path) -> None:
        """
        Apply hierarchical postprocessor with revert if it removes all headers.

        The ResultPostprocessor tries to extract TOC from PDF metadata first.
        If metadata extraction removes most headers, we revert to original Docling headers.
        """
        apply_hierarchical_postprocessor(self, result, filepath)

    def _normalize_toc_mixed_levels(self, toc_string: str) -> str:
        """Normalize mixed numbered/non-numbered TOC levels."""
        return normalize_toc_mixed_levels(toc_string)

    def _generate_toc_from_docling(self, result: Any) -> str:
        """
        Generate TOC string from Docling result.

        Args:
            result: Docling parsing result

        Returns:
            TOC string
        """
        return generate_toc_from_docling(self, result)

    def _write_toc_to_file(self, toc_string: str, output_folder: str) -> None:
        """
        Write TOC string to toc.txt file, cleaning comparison markers if present.

        Args:
            toc_string: TOC content to write
            output_folder: Directory where toc.txt should be written
        """
        write_toc_to_file(self, toc_string, output_folder)

    def _check_if_hierarchy_exists(self, result: Any) -> bool:
        """
        Check if document has meaningful heading hierarchy.

        Returns False if all headings are at the same level (flat structure).
        """
        return check_if_hierarchy_exists(result)

    def _infer_level_from_numbering(self, text: str) -> Optional[int]:
        """Infer heading level from section numbering pattern."""
        return infer_level_from_numbering(text)

    def _get_top_level_sections(self) -> set:
        """Known top-level section names."""
        return get_top_level_sections()

    def _extract_hybrid_headings(self, filepath: str, body_size: float) -> List[Dict]:
        """
        Extract headings using hybrid approach: PyMuPDF fonts + numbering patterns.

        Args:
            filepath: Path to PDF file
            body_size: Body text font size (for comparison)

        Returns:
            List of heading dicts with text, level, page, method
        """
        return extract_hybrid_headings(self, filepath, body_size)

    def _apply_hybrid_heading_detection(self, result: Any, filepath: Path) -> bool:
        """
        Apply hybrid heading detection as fallback when Docling fails to detect hierarchy.

        Only activates if:
        1. ENABLE_HYBRID_HEADING_DETECTION is true
        2. Document has enough pages (>= MIN_PAGES_FOR_HYBRID_HEADINGS)
        3. Docling/postprocessor produced flat heading structure
        4. Hybrid method finds hierarchy

        Returns:
            True if hybrid detection was applied, False otherwise
        """
        return apply_hybrid_heading_detection(self, result, filepath)

    def _save_images_metadata(self, document, output_folder: str) -> dict:
        """
        Save metadata for picture items (figures, charts, etc.).

        Creates images_metadata.json mapping picture index to file path + position info.
        This enables associating images with chunks during indexing.

        Args:
            document: Docling document with parsed content
            output_folder: Base output folder for parsed content

        Returns:
            Dict mapping picture index to metadata (path, page, bbox)
        """
        return save_images_metadata(self, document, output_folder)

    def _generate_thumbnail(
        self, filepath: str, output_folder: str, file_format: str
    ) -> None:
        """
        Generate a thumbnail from the first page of the document.

        Creates thumbnail.png in the output folder with a max dimension of 300px.

        Args:
            filepath: Path to the source document
            output_folder: Directory where thumbnail.png will be saved
            file_format: File format (pdf, docx, etc.)
        """
        try:
            # Only generate thumbnails for PDF files
            if file_format != "pdf":
                logger.debug("  Skipping thumbnail generation for non-PDF file")
                return

            # Open the PDF
            doc = fitz.open(filepath)
            if len(doc) == 0:
                logger.warning("  ⚠ Cannot generate thumbnail: PDF has no pages")
                doc.close()
                return

            # Get the first page
            page = doc[0]

            # Calculate zoom to get ~300px max dimension
            # page.rect gives us page dimensions in points
            rect = page.rect
            max_dimension = max(rect.width, rect.height)
            target_size = 300
            zoom = target_size / max_dimension

            # Create transformation matrix for rendering
            mat = fitz.Matrix(zoom, zoom)

            # Render page to pixmap (image)
            pix = page.get_pixmap(matrix=mat)

            # Save as PNG
            thumbnail_path = Path(output_folder) / "thumbnail.png"
            pix.save(str(thumbnail_path))

            doc.close()
            logger.info("  ✓ Generated thumbnail: thumbnail.png")

        except Exception as e:
            logger.warning("  ⚠ Failed to generate thumbnail: %s", e)

    def _parse_chunks(self, chunk_files: list[dict]) -> list[dict]:
        """Parse PDF chunks with optional timeouts."""
        return parse_chunks(self, chunk_files)

    def _parse_with_chunking(
        self, filepath: str, output_folder: str
    ) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], str, str]:
        """Parse large PDF using chunking for memory efficiency."""
        return parse_with_chunking(self, filepath, output_folder)

    def _split_pdf(self, filepath: str) -> Tuple[list, str]:
        """Split PDF into chunks."""
        return split_pdf(self, filepath)

    def _parse_chunk(self, chunk_path: str, chunk_num: int, start_page: int) -> Dict:
        """Parse a single PDF chunk."""
        return parse_chunk(self, chunk_path, chunk_num, start_page)

    def _merge_chunks(
        self,
        chunk_results: list,
        output_folder: str,
        pdf_filename: str,
        chunk_files: list,
    ) -> Tuple[str, str]:
        """Merge parsed chunk results including JSON for indexer."""
        return merge_chunks(
            self, chunk_results, output_folder, pdf_filename, chunk_files
        )

    def _cleanup_chunks(self, chunk_files: list, temp_dir: str) -> None:
        """Clean up temporary chunk files."""
        cleanup_chunks(chunk_files, temp_dir)

    def teardown(self) -> None:
        """Release Docling resources."""
        self._converter = None
        super().teardown()
