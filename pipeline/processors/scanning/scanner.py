"""
scanner.py - File scanner processor for syncing filesystem to Qdrant.

Scans the data directory for documents and syncs metadata to Qdrant.
Unlike other processors, this operates on the filesystem, not individual documents.
"""

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client.http import models

from pipeline.db import Database, get_db, make_stage
from pipeline.db.postgres_client import PostgresClient
from pipeline.processors.base import BaseProcessor
from pipeline.processors.scanning.scanner_mapping import ScannerMappingMixin
from pipeline.utilities.id_utils import generate_doc_id

logger = logging.getLogger(__name__)

# Regex to match URL suffix in titles (e.g., " - https://example.com/...")
URL_SUFFIX_PATTERN = re.compile(r"\s*-\s*https?://[^\s]+$")


def _make_relative_path(path: str) -> str:
    """
    Convert an absolute path to a relative path starting with 'data/'.

    Handles paths like:
    - /mnt/files/evaluation-db/uneg/pdfs/... -> data/uneg/pdfs/...
    - /mnt/data/uneg/pdfs/... -> data/uneg/pdfs/...
    - ./data/uneg/pdfs/... -> data/uneg/pdfs/...
    - data/uneg/pdfs/... -> data/uneg/pdfs/... (unchanged)

    This ensures consistent path storage regardless of mount location.
    """
    path_str = str(path).replace("\\", "/")

    # Find the data source folder (uneg, gcf, etc.) in the path
    # Pattern: .../uneg/pdfs/... or .../uneg/cache/...
    match = re.search(r"/(\w+)/(pdfs|cache)/", path_str)
    if match:
        # Find where this match starts and construct relative path
        idx = match.start()
        return "data" + path_str[idx:]

    # Preserve integration test paths under tests/integration/data
    tests_marker = "/tests/integration/data/"
    tests_idx = path_str.find(tests_marker)
    if tests_idx != -1:
        return path_str[tests_idx + 1 :]

    # Fallback: look for /data/ marker
    data_marker = "/data/"
    idx = path_str.find(data_marker)
    if idx != -1:
        return path_str[idx + 1 :]  # Skip the leading /

    # Handle ./data/ prefix
    if path_str.startswith("./data/"):
        return path_str[2:]

    # Already relative
    if path_str.startswith("data/"):
        return path_str

    return path_str


def clean_title(title: str) -> str:
    """Remove URL suffix from title if present."""
    if not title:
        return title
    return URL_SUFFIX_PATTERN.sub("", title).strip()


class ScanProcessor(ScannerMappingMixin, BaseProcessor):
    """
    File scanner processor for syncing filesystem to Qdrant.

    Scans the data/pdfs directory for:
    - JSON metadata files (Primary Source of Truth)
    - Checks for corresponding Content files (PDF, DOCX, DOC)
    - Checks for corresponding Error files (.error)

    Syncs changes to Qdrant based on file/metadata checksums.
    """

    name = "ScanProcessor"
    stage_name = "download"

    def __init__(self, base_dir: str = "./data/pdfs", db: Database = None):
        """
        Initialize scanner configuration.

        Args:
            base_dir: Base directory to scan for documents
            db: Database instance (if None, uses default from get_db())
        """
        super().__init__()
        self.base_dir = base_dir
        self.db = db or get_db()
        self.pg: Optional[PostgresClient] = None
        if isinstance(self.db, Database):
            self.pg = PostgresClient(self.db.data_source)
        self.batch_size = 50  # Number of documents to upsert in one batch

    def process_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Not used for scanner - use scan_and_sync() instead.

        Scanner operates on filesystem, not individual documents.
        """
        raise NotImplementedError(
            "ScanProcessor works on filesystem. Use scan_and_sync() instead."
        )

    def _load_existing_checksums(self) -> Dict[str, Dict[str, Any]]:
        """
        Pre-fetch all document checksums from Qdrant in batch.

        Returns:
            Dict mapping doc_id to checksum fields
        """
        logger.info("Loading existing document checksums from Postgres...")
        checksums = {}
        count = 0
        if not self.pg:
            logger.info("Skipping Postgres checksum preload (no Postgres client).")
            return {}
        sys_fields_by_doc = self.pg.fetch_doc_sys_fields()
        for doc_id, _doc in self.db.get_all_documents_with_ids():
            sys_fields = sys_fields_by_doc.get(str(doc_id), {})
            checksums[str(doc_id)] = {
                "sys_file_checksum": sys_fields.get("sys_file_checksum"),
                "sys_metadata_checksum": sys_fields.get("sys_metadata_checksum"),
                "sys_error_checksum": sys_fields.get("sys_error_checksum"),
                # Track status to avoid resetting progressed docs to downloaded.
                "sys_status": sys_fields.get("sys_status"),
            }
            count += 1
        logger.info("  Loaded checksums for %s documents", count)
        return checksums

    def scan_and_sync(self) -> Dict[str, Any]:
        """
        Scan directory and sync documents to Qdrant.
        Iterates over JSON metadata files to discover content.

        Returns:
            Dict with statistics about the scan
        """
        self.ensure_setup()

        logger.info("=" * 60)
        logger.info("SCANNING DATA DIRECTORY AND SYNCING TO QDRANT")
        logger.info("=" * 60)

        # Scan for metadata files
        json_files = self._scan_metadata_files()

        if not json_files:
            logger.info("No metadata files found. Nothing to sync.")
            return {"new": 0, "errors": 0, "total": 0}

        # Pre-fetch all checksums in one batch (much faster than per-doc queries)
        existing_checksums = self._load_existing_checksums()

        stats = {
            "new": 0,
            "file_changed": 0,
            "metadata_changed": 0,
            "both_changed": 0,
            "unchanged": 0,
            "no_metadata": 0,
            "errors": 0,
            "download_errors_new": 0,
            "download_errors_unchanged": 0,
            "duplicates": 0,
        }

        total_files = len(json_files)
        logger.info("Processing %s metadata files...", total_files)

        # Pending batch for upsert
        upsert_batch = []  # List of (doc_id, metadata)

        for idx, json_path in enumerate(json_files):
            if idx % 100 == 0 and idx > 0:
                logger.info("  Processed %s/%s files...", idx, total_files)

            # Process Metadata File
            result = self._process_metadata_file(json_path, stats, existing_checksums)

            if result:
                upsert_batch.append(result)

            # Flush batch if full
            if len(upsert_batch) >= self.batch_size:
                self._flush_batch(upsert_batch)
                upsert_batch = []

        # Flush remaining
        if upsert_batch:
            self._flush_batch(upsert_batch)

        # Post-process: detect and mark duplicates
        duplicate_count = self._mark_duplicates()
        stats["duplicates"] = duplicate_count

        self._print_stats(stats, total_files)
        return stats

    def scan_and_sync_single(
        self, report_path: Optional[str] = None, doc_id: Optional[str] = None
    ) -> bool:
        """
        Scan a single metadata file and sync the matching document to Qdrant.

        Used when orchestrator is invoked with --file or --file-id to avoid a full scan.
        """
        self.ensure_setup()

        if not report_path and not doc_id:
            logger.warning("scan_and_sync_single called without report_path or doc_id")
            return False

        report_resolved = self._resolve_report_path(report_path)
        if report_path and not report_resolved:
            return False

        json_files = self._collect_metadata_json_files(report_resolved)

        if not json_files:
            logger.warning("No metadata files found for targeted scan.")
            return False

        existing_checksums = self._load_existing_checksums()
        stats = {
            "new": 0,
            "file_changed": 0,
            "metadata_changed": 0,
            "both_changed": 0,
            "unchanged": 0,
            "no_metadata": 0,
            "errors": 0,
            "download_errors_new": 0,
            "download_errors_unchanged": 0,
            "duplicates": 0,
        }

        matched = self._scan_single_json_files(
            json_files,
            report_resolved,
            doc_id,
            stats,
            existing_checksums,
        )

        if not matched:
            logger.warning("Target document not found in metadata.")
            return False

        return True

    def _resolve_report_path(self, report_path: Optional[str]) -> Optional[Path]:
        if not report_path:
            return None
        report_resolved = Path(report_path).resolve()
        if not report_resolved.exists():
            logger.warning("Report path does not exist: %s", report_resolved)
            return None
        return report_resolved

    def _collect_metadata_json_files(
        self, report_resolved: Optional[Path]
    ) -> List[Path]:
        if report_resolved:
            search_dir = report_resolved.parent
            return [
                p
                for p in search_dir.rglob("*.json")
                if "parsed" not in p.parts and "cache" not in p.parts
            ]
        return self._scan_metadata_files()

    def _matches_doc_id(self, metadata: Dict[str, Any], doc_id: Optional[str]) -> bool:
        if not doc_id:
            return True
        candidate_id = (
            metadata.get("node_id") or metadata.get("id") or metadata.get("doc_id")
        )
        return str(candidate_id) == str(doc_id)

    def _matches_report_path(
        self,
        json_path: Path,
        metadata: Dict[str, Any],
        report_resolved: Optional[Path],
    ) -> bool:
        if not report_resolved:
            return True
        content_file = self._resolve_content_file(json_path, metadata)
        if not content_file:
            return False
        return content_file.resolve() == report_resolved

    def _upsert_single_result(self, result: Optional[tuple]) -> None:
        if not result:
            return
        doc_id_value, payload = result
        self.db.upsert_document(doc_id_value, payload)

    def _scan_single_json_files(
        self,
        json_files: List[Path],
        report_resolved: Optional[Path],
        doc_id: Optional[str],
        stats: Dict[str, int],
        existing_checksums: Dict[str, Dict[str, Any]],
    ) -> bool:
        for json_path in json_files:
            metadata = self._load_metadata_from_json(str(json_path))
            if not metadata:
                continue
            if not self._matches_doc_id(metadata, doc_id):
                continue
            if not self._matches_report_path(json_path, metadata, report_resolved):
                continue
            result = self._process_metadata_file(json_path, stats, existing_checksums)
            self._upsert_single_result(result)
            return True
        return False

    def _flush_batch(self, batch: List[Any]) -> None:
        """Helper to upsert a batch of documents."""
        if not batch:
            return

        points = []
        for doc_id, payload in batch:
            # Construct Qdrant Point
            points.append(
                models.PointStruct(
                    id=doc_id,
                    payload=payload,
                    vector={},  # Scan currently doesn't add vectors, but we must respect existing?
                    # Upsert usually overwrites if same ID?
                    # db.upsert_document typically uses 'Update' or 'Upload Points'
                )
            )

        # We need to access the qdrant client directly to do batch upsert
        # DB wrapper might not expose it easily, but usually self.db.client is accessible
        try:
            # Using client.upsert which handles batches
            self.db.client.upsert(
                collection_name=self.db.documents_collection, points=points, wait=False
            )
            logger.info("  -> Batched upsert of %s documents", len(points))
        except Exception as e:
            logger.error("Failed to upsert batch: %s", e)
            # Fallback to single? Or just log.
            # If batch fails, maybe try one by one.
            for doc_id, payload in batch:
                try:
                    self.db.upsert_document(doc_id, payload)
                except Exception as ex:
                    logger.error("Single upsert failed for %s: %s", doc_id, ex)

    def _scan_metadata_files(self) -> List[Path]:
        """Scan for JSON metadata files."""
        base_path = Path(self.base_dir)
        if not base_path.exists():
            logger.warning("Data directory not found: %s", self.base_dir)
            return []

        # Filter out files in 'parsed' and 'cache' directories
        # Using rglob("*") and checking extension to handle potential unicode issues if needed,
        # but rglob("*.json") is usually safe enough.
        # logic from populate script implies strict check.
        json_files = []
        for f in base_path.rglob("*"):
            if not f.name.endswith(".json"):
                continue
            if "parsed" in f.parts or "cache" in f.parts:
                continue
            json_files.append(f)

        json_files = sorted(json_files)

        logger.info(
            "Found %s JSON metadata files in %s", len(json_files), self.base_dir
        )
        return json_files

    def _compute_file_checksum(self, filepath: str) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logger.error("Error computing checksum for %s: %s", filepath, e)
            return ""

    def _compute_json_checksum(self, metadata: Dict) -> str:
        """Compute checksum of metadata JSON (normalized)."""
        try:
            json_str = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(json_str.encode()).hexdigest()
        except Exception as e:
            logger.error("Error computing JSON checksum: %s", e)
            return ""

    def _load_metadata_from_json(self, json_path: str) -> Optional[Dict]:
        """Load metadata from JSON file and clean title."""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Clean title to remove any URL suffixes
            if "title" in data and data["title"]:
                data["title"] = clean_title(data["title"])

            return data
        except Exception as e:
            logger.error("Error loading metadata from %s: %s", json_path, e)
            return None

    def _resolve_content_file(self, json_path: Path, metadata: Dict) -> Optional[Path]:
        content_file = self._resolve_content_from_metadata(json_path, metadata)
        if not content_file:
            content_file = self._resolve_content_by_extension(json_path)
        if not content_file:
            content_file = self._resolve_content_by_stem(json_path)
        return content_file

    def _resolve_content_from_metadata(
        self, json_path: Path, metadata: Dict
    ) -> Optional[Path]:
        target_filename = metadata.get("filename")
        if not target_filename:
            return None
        candidate = json_path.parent / target_filename
        if candidate.exists():
            return candidate
        stem = Path(target_filename).stem
        suffix = Path(target_filename).suffix
        stem_nfc = unicodedata.normalize("NFC", stem)
        if json_path.parent.exists():
            for text_file in json_path.parent.iterdir():
                if text_file.suffix.lower() != suffix.lower():
                    continue
                if unicodedata.normalize("NFC", text_file.stem) == stem_nfc:
                    return text_file
        return None

    def _resolve_content_by_extension(self, json_path: Path) -> Optional[Path]:
        for ext in [".pdf", ".PDF", ".docx", ".DOCX", ".doc", ".DOC"]:
            candidate = json_path.with_suffix(ext)
            if candidate.exists():
                return candidate
        return None

    def _resolve_content_by_stem(self, json_path: Path) -> Optional[Path]:
        parent = json_path.parent
        stem = json_path.stem
        stem_nfc = unicodedata.normalize("NFC", stem)
        if parent.exists():
            for text_file in parent.iterdir():
                if text_file.suffix.lower() not in [".pdf", ".docx", ".doc"]:
                    continue
                if unicodedata.normalize("NFC", text_file.stem) == stem_nfc:
                    return text_file
        return None

    def _resolve_status_and_path(
        self, content_file: Optional[Path], error_file: Path
    ) -> Tuple[Optional[str], Optional[Path], Optional[str]]:
        if content_file:
            return "downloaded", content_file, str(content_file)
        if error_file.exists():
            return "download_error", error_file, str(error_file)
        return None, None, None

    def _build_doc_id(
        self, metadata: Dict, normalized_path: str, current_status: str
    ) -> str:
        if current_status == "download_error":
            url = metadata.get("pdf_url", metadata.get("report_url", ""))
            return generate_doc_id(url) if url else generate_doc_id(normalized_path)
        return generate_doc_id(normalized_path)

    def _read_error_file(self, file_to_hash: Path) -> Tuple[str, str]:
        error_message = ""
        error_checksum = ""
        try:
            with open(file_to_hash, "r", encoding="utf-8") as f:
                content = f.read().strip()
            try:
                error_data = json.loads(content)
                if isinstance(error_data, dict):
                    error_message = (
                        error_data.get("error_message")
                        or error_data.get("download_error")
                        or content
                    )
                else:
                    error_message = content
            except json.JSONDecodeError:
                error_message = content
            error_checksum = hashlib.sha256(error_message.encode()).hexdigest()
        except Exception as e:
            logger.warning("Error reading error file %s: %s", file_to_hash, e)
            error_message = "Unknown error"
        return error_message, error_checksum

    def _valid_progress_states(self) -> set:
        return {
            "downloaded",
            "parsing",
            "parsed",
            "summarizing",
            "summarized",
            "tagging",
            "tagged",
            "indexing",
            "indexed",
        }

    def _evaluate_existing(
        self,
        existing: Dict[str, Any],
        current_status: str,
        file_checksum: str,
        metadata_checksum: str,
        error_checksum: str,
    ) -> Tuple[bool, str]:
        old_status = existing.get("sys_status")
        valid_progress_states = self._valid_progress_states()
        status_changed = False
        if current_status == "downloaded":
            if old_status not in valid_progress_states:
                status_changed = True
        elif current_status != old_status:
            status_changed = True
        if status_changed:
            return True, "status_change"

        if current_status == "downloaded":
            old_f_sum = existing.get("sys_file_checksum")
            old_m_sum = existing.get("sys_metadata_checksum")
            file_changed = bool(old_f_sum) and file_checksum != old_f_sum
            meta_changed = bool(old_m_sum) and metadata_checksum != old_m_sum
            if file_changed and meta_changed:
                return True, "both"
            if file_changed:
                return True, "file"
            if meta_changed:
                return True, "metadata"
            return False, ""

        old_e_sum = existing.get("sys_error_checksum")
        old_m_sum = existing.get("sys_metadata_checksum")
        meta_matches = not old_m_sum or old_m_sum == metadata_checksum
        error_matches = not old_e_sum or old_e_sum == error_checksum
        if not (meta_matches and error_matches):
            return True, "download_error"
        return False, ""

    def _build_qdrant_metadata(
        self,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        src_fields, map_fields = self._apply_field_mapping(metadata)
        return {**src_fields, **map_fields}

    def _build_sys_fields(
        self,
        *,
        normalized_path: str,
        current_status: str,
        effective_status: str,
        metadata_checksum: str,
        file_checksum: str,
        error_message: str,
        error_checksum: str,
        change_type: str,
    ) -> Dict[str, Any]:
        stage_success = current_status == "downloaded"
        download_stage = make_stage(
            success=stage_success,
            error=error_message if not stage_success else None,
        )
        sys_fields: Dict[str, Any] = {
            "sys_filepath": normalized_path,
            "sys_status": effective_status,
            "sys_metadata_checksum": metadata_checksum,
            "sys_stages": {"download": download_stage},
        }
        if current_status == "downloaded":
            sys_fields["sys_file_checksum"] = file_checksum
            if change_type:
                sys_fields["sys_last_change_type"] = change_type
        else:
            sys_fields["sys_download_error"] = error_message
            sys_fields["sys_error_file"] = normalized_path
            sys_fields["sys_error_checksum"] = error_checksum
        return sys_fields

    def _should_upsert_and_update_stats(
        self,
        existing: Optional[Dict[str, Any]],
        current_status: str,
        file_checksum: str,
        metadata_checksum: str,
        error_checksum: str,
        stats: Dict[str, int],
        file_path_display: str,
    ) -> Tuple[bool, str]:
        if not existing:
            if current_status == "downloaded":
                stats["new"] += 1
                logger.info("  ➕ NEW: %s", file_path_display)
            else:
                stats["download_errors_new"] += 1
            return True, "new"

        should_upsert, change_type = self._evaluate_existing(
            existing,
            current_status,
            file_checksum,
            metadata_checksum,
            error_checksum,
        )
        if should_upsert and change_type == "status_change":
            if current_status == "downloaded":
                stats["new"] += 1
            else:
                stats["download_errors_new"] += 1
        elif should_upsert and change_type == "both":
            stats["both_changed"] += 1
        elif should_upsert and change_type == "file":
            stats["file_changed"] += 1
        elif should_upsert and change_type == "metadata":
            stats["metadata_changed"] += 1
        elif should_upsert and change_type == "download_error":
            stats["download_errors_new"] += 1
        else:
            if current_status == "downloaded":
                stats["unchanged"] += 1
            else:
                stats["download_errors_unchanged"] += 1
        return should_upsert, change_type

    def _compute_checksums(
        self, current_status: str, file_to_hash: Path
    ) -> tuple[str, str, str]:
        if current_status == "downloaded":
            return self._compute_file_checksum(str(file_to_hash)), "", ""
        error_message, error_checksum = self._read_error_file(file_to_hash)
        return "", error_checksum, error_message

    def _resolve_effective_status(
        self, current_status: str, existing: Optional[Dict[str, Any]]
    ) -> str:
        existing_status = existing.get("sys_status") if existing else None
        if (
            current_status == "downloaded"
            and existing_status
            and existing_status != "download_error"
        ):
            return existing_status
        return current_status

    def _upsert_doc_payload(
        self,
        *,
        doc_id: str,
        metadata: Dict[str, Any],
        normalized_path: str,
        current_status: str,
        effective_status: str,
        metadata_checksum: str,
        file_checksum: str,
        error_message: str,
        error_checksum: str,
        change_type: str,
    ) -> Dict[str, Any]:
        qdrant_metadata = self._build_qdrant_metadata(metadata)
        sys_fields = self._build_sys_fields(
            normalized_path=normalized_path,
            current_status=current_status,
            effective_status=effective_status,
            metadata_checksum=metadata_checksum,
            file_checksum=file_checksum,
            error_message=error_message,
            error_checksum=error_checksum,
            change_type=change_type,
        )
        _, map_fields = self._apply_field_mapping(metadata)
        sys_summary = metadata.get("sys_summary")
        if "sys_summary" in sys_fields:
            sys_fields.pop("sys_summary", None)
        if not self.pg:
            return {**qdrant_metadata, **sys_fields}
        self.pg.upsert_doc(
            doc_id=str(doc_id),
            src_doc_raw_metadata=metadata,
            map_fields=map_fields,
            sys_summary=sys_summary,
            sys_fields=sys_fields,
        )
        return qdrant_metadata

    def _process_metadata_file(
        self, json_path: Path, stats: Dict, existing_checksums: Dict[str, Dict]
    ) -> Optional[tuple]:
        """
        Process a single metadata file and prepare result for upsert.
        Returns (doc_id, metadata) if upsert is needed, else None.
        """
        metadata = self._load_metadata_from_json(str(json_path))
        if not metadata:
            stats["errors"] += 1
            return None

        content_file = self._resolve_content_file(json_path, metadata)

        # Check for error file
        error_file = json_path.with_suffix(".error")

        current_status, file_to_hash, file_path_display = self._resolve_status_and_path(
            content_file, error_file
        )
        if not current_status or not file_to_hash or not file_path_display:
            return None

        # Generate Doc ID
        # Logic must match scripts/migration/populate_qdrant_from_files.py
        normalized_path = _make_relative_path(file_path_display)

        doc_id = self._build_doc_id(metadata, normalized_path, current_status)

        # PROCESSING LOGIC
        # ---------------------------------------------------------

        metadata_checksum = self._compute_json_checksum(metadata)

        file_checksum, error_checksum, error_message = self._compute_checksums(
            current_status, file_to_hash
        )

        existing = existing_checksums.get(doc_id)
        effective_status = self._resolve_effective_status(current_status, existing)

        should_upsert, change_type = self._should_upsert_and_update_stats(
            existing,
            current_status,
            file_checksum,
            metadata_checksum,
            error_checksum,
            stats,
            file_path_display,
        )

        if should_upsert:
            qdrant_metadata = self._upsert_doc_payload(
                doc_id=str(doc_id),
                metadata=metadata,
                normalized_path=normalized_path,
                current_status=current_status,
                effective_status=effective_status,
                metadata_checksum=metadata_checksum,
                file_checksum=file_checksum,
                error_message=error_message,
                error_checksum=error_checksum,
                change_type=change_type,
            )

            if change_type:
                logger.info("  🔄 Updated (%s): %s", change_type, file_path_display)

            return (doc_id, qdrant_metadata)

        return None

    def _mark_duplicates(self) -> int:
        """
        Post-process: detect and mark duplicate documents.

        Groups documents by file_checksum. For each group with multiple documents,
        keeps the first (by filepath sort order) as the original and marks others
        as is_duplicate=True.

        Returns:
            Number of documents marked as duplicates
        """
        logger.info("\n--- Detecting duplicates by file checksum ---")

        if not self.pg:
            logger.info("Skipping duplicate scan (no Postgres client).")
            return 0
        checksum_groups = self._collect_checksum_groups()

        # Find duplicates and mark them
        duplicates_marked = 0
        duplicates_already = 0

        for _checksum, docs in checksum_groups.items():
            marked, already = self._mark_duplicate_group(docs)
            duplicates_marked += marked
            duplicates_already += already

        total_duplicates = duplicates_marked + duplicates_already
        if total_duplicates > 0:
            duplicate_groups = len([g for g in checksum_groups.values() if len(g) > 1])
            logger.info(
                "  Found %s duplicate groups (%s duplicate files)",
                duplicate_groups,
                total_duplicates,
            )
            if duplicates_marked > 0:
                logger.info("  Marked %s new duplicates", duplicates_marked)
        else:
            logger.info("  No duplicates found")

        return total_duplicates

    def _collect_checksum_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        checksum_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        sys_fields_by_doc = self.pg.fetch_doc_sys_fields() if self.pg else {}
        for doc_id, doc_payload in self.db.get_all_documents_with_ids():
            sys_fields = sys_fields_by_doc.get(str(doc_id), {})
            file_checksum = sys_fields.get("sys_file_checksum")
            if not file_checksum or sys_fields.get("sys_status") != "downloaded":
                continue
            checksum_groups[file_checksum].append(
                {
                    "id": doc_id,
                    "filepath": sys_fields.get("sys_filepath", ""),
                    "is_duplicate": doc_payload.get("is_duplicate", False),
                }
            )
        return checksum_groups

    def _mark_duplicate_group(self, docs: List[Dict[str, Any]]) -> Tuple[int, int]:
        if len(docs) <= 1:
            return 0, 0
        docs_sorted = sorted(docs, key=lambda d: d["filepath"])
        duplicates_marked = 0
        duplicates_already = 0
        for dup_doc in docs_sorted[1:]:
            if dup_doc["is_duplicate"]:
                duplicates_already += 1
                continue
            self.db.update_document(dup_doc["id"], {"is_duplicate": True})
            if self.pg:
                self.pg.merge_doc_sys_fields(
                    doc_id=str(dup_doc["id"]),
                    sys_fields={"is_duplicate": True},
                )
            duplicates_marked += 1
        return duplicates_marked, duplicates_already

    def _print_stats(self, stats: Dict, total_docs: int) -> None:
        """Print summary statistics."""
        logger.info("%s", "\n" + "=" * 60)
        logger.info("SCAN COMPLETE")
        logger.info("=" * 60)
        logger.info("Documents - new:         %s", stats["new"])
        logger.info("Documents - file changed:%s", stats["file_changed"])
        logger.info("Documents - meta changed:%s", stats["metadata_changed"])
        logger.info("Documents - both changed:%s", stats["both_changed"])
        logger.info("Documents - unchanged:   %s", stats["unchanged"])
        logger.info("Documents - duplicates:  %s", stats["duplicates"])
        # logger.info("Documents - no metadata: %s", stats["no_metadata"])
        logger.info("Download errors - new:   %s", stats["download_errors_new"])
        logger.info("Download errors - unchg: %s", stats["download_errors_unchanged"])
        logger.info("Processing errors:       %s", stats["errors"])
        logger.info("Total metadata scanned:  %s", total_docs)
        logger.info("=" * 60)
