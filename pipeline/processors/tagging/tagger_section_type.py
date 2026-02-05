"""Section type tagger implementation."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastembed import TextEmbedding

from pipeline.db import Database, PostgresClient
from pipeline.processors.tagging.tagger_base import BaseTagger
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from pipeline.processors.tagging.tagger_llm import call_llm_for_toc
from pipeline.processors.tagging.tagger_rules import (
    apply_keyword_locking,
    apply_sequence_rules,
    propagate_hierarchy,
)
from pipeline.processors.tagging.tagger_toc import (
    build_normalized_title_to_indices,
    ensure_label_is_valid,
    format_toc_line,
    parse_toc,
    select_toc_entry_by_heading_match,
    select_toc_entry_by_page,
)

logger = logging.getLogger(__name__)


class SectionTypeTagger(BaseTagger):
    """
    Labels chunks with `section_type` using TOC + deterministic rules + optional LLM completion.

    The only input TOC field is document["toc"], containing lines like:
      [H2] Heading Title | page 12

    Page numbers may be missing for some lines. Headings may repeat.
    """

    name = "SectionTypeTagger"
    tag_field = "tag_section_type"

    def __init__(
        self,
        embedding_model: Optional[TextEmbedding] = None,
        llm_config: Dict[str, Any] = None,
    ):
        super().__init__(embedding_model)
        self.llm_config = llm_config or {}
        self._database: Optional[Database] = None
        self._pg: Optional[PostgresClient] = None

        # Cache by document identifier. Each value is a dict:
        # {
        #   "toc_entries": List[Dict[str, Any]],
        #   "labels_by_index": Dict[int, str],
        #   "normalized_title_to_indices": Dict[str, List[int]],
        #   "is_saved_to_database": bool
        # }
        self._document_cache: Dict[str, Dict[str, Any]] = {}

    def set_db(self, database: Database) -> None:
        """Attach a database instance for TOC persistence."""
        self._database = database
        self._pg = PostgresClient(database.data_source)

    def setup(self) -> None:
        """Initialize tagger resources."""
        logger.info("SectionTypeTagger initialized (Unified Taxonomy)")

    def _parse_toc(self, toc_text: str) -> List[Dict[str, Any]]:
        """Backwards-compatible wrapper for TOC parsing."""
        return parse_toc(toc_text)

    def _apply_keyword_locking(
        self, toc_entries: List[Dict[str, Any]]
    ) -> Dict[int, str]:
        """Backwards-compatible wrapper for keyword locking."""
        return apply_keyword_locking(toc_entries)

    def _propagate_hierarchy(
        self, entries: List[Dict[str, Any]], labels: Dict[int, str]
    ) -> Dict[int, str]:
        """Backwards-compatible wrapper for hierarchy propagation."""
        return propagate_hierarchy(entries, labels)

    def _get_document_identifier(self, document: Dict[str, Any]) -> Optional[str]:
        identifier = (
            document.get("id") or document.get("node_id") or document.get("doc_id")
        )
        return str(identifier) if identifier is not None else None

    def _get_total_pages(self, document: Dict[str, Any]) -> Optional[int]:
        total_pages = document.get("page_count")
        if total_pages is None:
            total_pages = document.get("sys_page_count")
        return total_pages

    def _restore_labels_from_existing(
        self, document_identifier: str, document: Dict[str, Any]
    ) -> Optional[Tuple[List[Dict[str, Any]], Dict[int, str], bool]]:
        existing_toc_classified = document.get("sys_toc_classified")
        if not existing_toc_classified:
            return None

        toc_text = document.get("sys_toc", "") or ""
        toc_entries = parse_toc(toc_text)

        if not toc_entries:
            return None

        classified_lines = [
            line for line in existing_toc_classified.splitlines() if line.strip()
        ]

        if len(classified_lines) != len(toc_entries):
            return None

        restored_labels: Dict[int, str] = {}
        for i, line in enumerate(classified_lines):
            line_no_page = re.sub(
                r"\s*\|\s*page\s*\d+(?:\s*\([^)]+\))?(?:\s*\[Front\])?\s*$",
                "",
                line,
            )
            parts = line_no_page.rsplit("|", 1)
            if len(parts) < 2:
                return None

            label_candidate = parts[-1].strip()
            if label_candidate in SECTION_TYPES or label_candidate == "other":
                restored_labels[toc_entries[i]["index"]] = label_candidate
            else:
                return None

        normalized_title_to_indices = build_normalized_title_to_indices(toc_entries)
        final_labels = apply_sequence_rules(
            entries=toc_entries,
            labels=restored_labels,
            document=document,
        )
        if final_labels != restored_labels:
            restored_labels = final_labels
            should_resave = True
        has_roman_in_toc = any(entry.get("roman") for entry in toc_entries)
        has_roman_in_classified = any(
            re.search(r"\|\s*page\s*\d+\s*\([^)]+\)\s*(?:\[Front\])?\s*$", line)
            for line in classified_lines
        )
        has_fm_in_toc = any(entry.get("fm") for entry in toc_entries)
        has_fm_in_classified = any(
            re.search(r"\[Front\]\s*$", line) for line in classified_lines
        )
        should_resave = (has_roman_in_toc and not has_roman_in_classified) or (
            has_fm_in_toc and not has_fm_in_classified
        )
        self._document_cache[document_identifier] = {
            "toc_entries": toc_entries,
            "labels_by_index": restored_labels,
            "normalized_title_to_indices": normalized_title_to_indices,
            "is_saved_to_database": not should_resave,
        }
        logger.info("Used existing toc_classified for document %s", document_identifier)
        return toc_entries, restored_labels, should_resave

    def _compute_document_toc_labels(
        self, document: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
        """Compute TOC entries and labels for a document."""
        document_identifier = self._get_document_identifier(document)
        if not document_identifier:
            return [], {}

        if document_identifier in self._document_cache:
            cached = self._document_cache[document_identifier]
            return cached["toc_entries"], cached["labels_by_index"]

        restored = self._restore_labels_from_existing(document_identifier, document)
        if restored:
            toc_entries, labels_by_index, should_resave = restored
            if should_resave:
                self._document_cache[document_identifier][
                    "is_saved_to_database"
                ] = False
            return toc_entries, labels_by_index

        toc_text = document.get("sys_toc", "") or ""
        document_title = document.get("map_title", "Untitled")

        toc_entries = parse_toc(toc_text)
        if not toc_entries:
            self._document_cache[document_identifier] = {
                "toc_entries": [],
                "labels_by_index": {},
                "normalized_title_to_indices": {},
                "is_saved_to_database": False,
            }
            return [], {}

        normalized_title_to_indices = build_normalized_title_to_indices(toc_entries)

        # Locked labels by deterministic keyword rules
        locked_labels_by_index = apply_keyword_locking(toc_entries)

        # LLM fills remaining (if any missing), but may return only locked labels if it fails
        total_pages = self._get_total_pages(document)
        if len(locked_labels_by_index) < len(toc_entries):
            llm_labels_by_index = call_llm_for_toc(
                document_title=document_title,
                toc_entries=toc_entries,
                locked_labels_by_index=locked_labels_by_index,
                llm_config=self.llm_config,
                total_pages=total_pages,
                retry_on_failure=True,
            )
        else:
            llm_labels_by_index = dict(locked_labels_by_index)

        # Merge: locked overrides LLM
        merged_labels_by_index = dict(llm_labels_by_index)
        merged_labels_by_index.update(locked_labels_by_index)

        final_labels_by_index = propagate_hierarchy(
            entries=toc_entries,
            labels=merged_labels_by_index,
        )

        final_labels_by_index = apply_sequence_rules(
            entries=toc_entries,
            labels=final_labels_by_index,
            document=document,
        )

        self._document_cache[document_identifier] = {
            "toc_entries": toc_entries,
            "labels_by_index": final_labels_by_index,
            "normalized_title_to_indices": normalized_title_to_indices,
            "is_saved_to_database": False,
        }

        return toc_entries, final_labels_by_index

    def classify_document_toc(self, document: Dict[str, Any]) -> Dict[str, str]:
        """
        Classify document TOC and persist a classified TOC string to the database.

        Returns a legacy mapping from normalized_title -> label for compatibility.
        NOTE: When titles repeat, this legacy mapping will keep the last label for that title.
        Internal logic remains collision-safe via index-keyed labels.
        """
        document_identifier = self._get_document_identifier(document)
        if not document_identifier:
            logger.warning("No document identifier found; cannot classify TOC.")
            return {}

        toc_entries, labels_by_index = self._compute_document_toc_labels(document)
        if not toc_entries:
            return {}

        cached = self._document_cache.get(document_identifier)
        already_saved = bool(cached and cached.get("is_saved_to_database"))

        if self._database and not already_saved:
            toc_classified_lines = [
                format_toc_line(entry, labels_by_index.get(entry["index"], "other"))
                for entry in toc_entries
            ]
            toc_classified_text = "\n".join(toc_classified_lines)

            try:
                if self._pg is not None:
                    self._pg.merge_doc_sys_fields(
                        doc_id=str(document_identifier),
                        sys_fields={
                            "sys_toc_classified": toc_classified_text,
                            "sys_user_edited_section_types": False,
                        },
                    )
                    logger.info(
                        "Saved classified TOC for document %s", document_identifier
                    )
                    self._document_cache[document_identifier][
                        "is_saved_to_database"
                    ] = True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to save classified TOC for document %s: %s",
                    document_identifier,
                    exc,
                )

        # Build legacy mapping (normalized_title -> label) for any external compatibility needs.
        legacy_mapping: Dict[str, str] = {}
        for entry in toc_entries:
            legacy_mapping[entry["normalized_title"]] = labels_by_index[entry["index"]]
        return legacy_mapping

    def tag_chunk(
        self, chunk: Dict[str, Any], document: Dict[str, Any]
    ) -> Optional[str]:
        """
        Determine `section_type` for a chunk.

        Primary strategy:
        - If chunk has a page number and TOC contains pages: assign by TOC page ranges.

        Fallback strategy:
        - Match chunk headings to TOC titles (collision-safe using TOC indices).

        If no classification data is available: returns "other".
        """
        toc_entries, labels_by_index = self._compute_document_toc_labels(document)
        if not toc_entries or not labels_by_index:
            return "other"

        # Ensure classified TOC is persisted once per document (optional side effect).
        # This does not affect classification results.
        try:
            self.classify_document_toc(document)
        except Exception:  # pylint: disable=broad-exception-caught
            # Never fail chunk tagging due to persistence issues.
            pass

        chunk_page = chunk.get("sys_page_num")
        chunk_page_number: Optional[int]
        try:
            chunk_page_number = int(chunk_page) if chunk_page is not None else None
        except Exception:  # pylint: disable=broad-exception-caught
            chunk_page_number = None

        # Strategy 1: Page range selection
        if chunk_page_number is not None:
            best_entry = select_toc_entry_by_page(toc_entries, chunk_page_number)
            if best_entry is not None:
                selected_label = labels_by_index.get(best_entry["index"], "other")
                return ensure_label_is_valid(selected_label)

        # Strategy 2: Heading match fallback
        document_identifier = self._get_document_identifier(document)
        normalized_title_to_indices: Dict[str, List[int]] = {}
        if document_identifier and document_identifier in self._document_cache:
            normalized_title_to_indices = self._document_cache[document_identifier].get(
                "normalized_title_to_indices", {}
            )

        chunk_headings = chunk.get("sys_headings") or []
        if isinstance(chunk_headings, list):
            selected_index = select_toc_entry_by_heading_match(
                toc_entries=toc_entries,
                normalized_title_to_indices=normalized_title_to_indices,
                labels_by_index=labels_by_index,
                chunk_headings=chunk_headings,
                chunk_page_number=chunk_page_number,
            )
            if selected_index is not None:
                selected_label = labels_by_index.get(selected_index, "other")
                return ensure_label_is_valid(selected_label)

        return "other"
