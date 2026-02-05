"""
chunker.py - Document chunking processor with metadata enrichment.

Extracts the chunking logic from IndexProcessor into a focused, well-organized class.
Handles:
- Loading Docling documents and metadata
- Chunking documents using HybridChunker
- Enriching chunks with images, tables, and text elements
- Post-processing for inline references

Each major step is broken into focused helper methods with clear documentation.
"""

import json
import logging

# import os (removed unused import)
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument, ListItem
from dotenv import load_dotenv

from pipeline.processors.indexing.chunker_images import (
    add_images_to_chunk_elements,
    calculate_text_bbox_ranges,
    extract_chunk_images,
    filter_images_before_text,
    filter_table_metadata_text,
    should_include_image,
)
from pipeline.processors.indexing.chunker_maps import (
    build_table_index_map,
    build_text_elements_map,
)
from pipeline.processors.indexing.chunker_post import post_process_chunks

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
PAGE_HEIGHT = 842  # Standard PDF page height in points


class Chunker:
    """
    Document chunking processor with metadata enrichment.

    Responsibilities:
    1. Load Docling documents and associated metadata (images, tables)
    2. Chunk documents using HybridChunker
    3. Enrich chunks with visual elements (images, tables)
    4. Post-process chunks to detect inline references

    The chunking process is broken down into focused helper methods for clarity.
    """

    def __init__(
        self,
        tokenizer=None,
        chunker=None,
        dense_model_id=None,
        max_tokens=512,
        min_substantive_size=100,
    ):
        """
        Initialize chunker with tokenizer and HybridChunker instance.

        Args:
            tokenizer: Tokenizer for counting tokens (e.g., from AutoTokenizer)
            chunker: HybridChunker instance (if None, creates default)
            dense_model_id: Required if chunker is None.
            max_tokens: Max tokens for default chunker.
            min_substantive_size: Minimum characters for a chunk to be kept.
        """
        self._tokenizer = tokenizer
        self._chunker = chunker
        self.max_tokens = max_tokens
        self.min_substantive_size = min_substantive_size

        if self._chunker is None and tokenizer is not None:
            if not dense_model_id:
                raise ValueError(
                    "Chunker: dense_model_id required to create default chunker"
                )

            # Create default chunker with provided tokenizer
            self._chunker = HybridChunker(
                tokenizer=dense_model_id,
                max_tokens=max_tokens,
                merge_peers=True,
            )

    def chunk_document(self, json_path: str) -> List[Dict[str, Any]]:
        """
        Main entry point: Load document and split into enriched chunks.

        This method orchestrates the entire chunking process by calling
        focused helper methods in sequence.

        Uses HybridChunker with tokenization-aware refinements:
        - First pass: splits chunks only when needed (oversized w.r.t. tokens)
        - Second pass: merges chunks when possible (undersized with same headings)

        Args:
            json_path: Path to the Docling JSON file

        Returns:
            List of chunk dictionaries with text, metadata, and enriched elements
        """
        path = Path(json_path)
        if not path.exists():
            logger.error("Document not found: %s", json_path)
            return []

        try:
            # Step 1: Load document and all metadata
            doc_data = self._load_document_and_metadata(path)
            doc = doc_data["doc"]
            text_map = doc_data["text_map"]
            images_by_page = doc_data["images_by_page"]
            table_images_meta = doc_data["table_images_meta"]

            # Step 2: Build text elements map for chunk association
            _text_elements_by_page, fixed_text_map = build_text_elements_map(
                doc, PAGE_HEIGHT
            )

            # Step 3: Build table index map for table lookup
            table_index_map = build_table_index_map(doc, PAGE_HEIGHT)

            # Step 4: Chunk the document using HybridChunker
            chunks = self._chunk_with_hybrid_chunker(doc)

            # Step 5: Process each chunk to extract and enrich metadata
            processed_chunks = []
            for chunk_idx, chunk in enumerate(chunks):
                chunk_dict = self._process_single_chunk(
                    doc,
                    chunk,
                    chunk_idx,
                    text_map,
                    fixed_text_map,
                    table_index_map,
                    images_by_page,
                    table_images_meta,
                )
                if chunk_dict:
                    # Filter out non-substantive chunks (noise)
                    # Exclude ListItems and Headers from filtering to preserve structure

                    # Check for structural content (lists, headers)
                    has_structural_content = any(
                        e.get("label")
                        in ["list_item", "section_header", "caption", "table_caption"]
                        for e in chunk_dict.get("chunk_elements", [])
                    )

                    if (
                        len(chunk_dict["text"].strip()) < self.min_substantive_size
                        and not has_structural_content
                    ):
                        logger.debug(
                            "Skipping small chunk %s: %s chars",
                            chunk_idx,
                            len(chunk_dict["text"]),
                        )
                        continue

                    processed_chunks.append(chunk_dict)

            # Step 6: Post-process chunks to detect inline references
            processed_chunks = post_process_chunks(doc, processed_chunks)

            # Log summary
            logger.info("  Generated %s chunks", len(processed_chunks))

            return processed_chunks

        except Exception as e:
            logger.error("Error chunking document %s: %s", json_path, e, exc_info=True)
            return []

    def _load_document_and_metadata(self, path: Path) -> Dict[str, Any]:
        """
        Load Docling document and all associated metadata files.

        Loads:
        - Docling JSON document
        - Text map (for resolving chunk text references)
        - Table images metadata
        - Visual images metadata

        Args:
            path: Path to the Docling JSON file

        Returns:
            Dict with 'doc', 'text_map', 'table_images_meta', 'images_by_page'
        """
        # Load Docling Document from JSON
        doc = DoclingDocument.load_from_json(path)

        # Build text map from JSON for resolving text content
        # Chunker items have self_ref but no text attribute - we need to resolve them
        text_map = {}
        with open(path, "r", encoding="utf-8") as f:
            doc_json = json.load(f)
            for item in doc_json.get("texts", []):
                self_ref = item.get("self_ref")
                text = item.get("text", "")
                if self_ref and text:
                    text_map[self_ref] = text
        logger.info("Built text map with %s entries", len(text_map))

        # Load table images metadata if available
        table_images_path = path.parent / "tables" / "table_images.json"
        table_images_meta = {}
        if table_images_path.exists():
            with open(table_images_path, "r", encoding="utf-8") as f:
                table_images_meta = json.load(f)

        # Load images metadata if available
        images_meta_path = path.parent / "images" / "images_metadata.json"
        images_meta = {}
        if images_meta_path.exists():
            with open(images_meta_path, "r", encoding="utf-8") as f:
                images_meta = json.load(f)

        # Build images map by page for chunk association
        images_by_page: Dict[int, List[Dict[str, Any]]] = {}
        for _idx, img_data in images_meta.items():
            page = img_data.get("page")
            if page is not None:
                if page not in images_by_page:
                    images_by_page[page] = []
                images_by_page[page].append(
                    {
                        "path": img_data.get("path"),
                        "bbox": img_data.get("bbox"),
                        "page": page,
                        "position_hint": img_data.get("position_hint"),
                    }
                )

        return {
            "doc": doc,
            "text_map": text_map,
            "table_images_meta": table_images_meta,
            "images_by_page": images_by_page,
        }

    def _build_text_elements_map(
        self, doc: DoclingDocument
    ) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[str, str]]:
        return build_text_elements_map(doc, PAGE_HEIGHT)

    def _build_table_index_map(self, doc: DoclingDocument) -> Dict[str, Dict[str, Any]]:
        return build_table_index_map(doc, PAGE_HEIGHT)

    def _chunk_with_hybrid_chunker(self, doc: DoclingDocument) -> List[Any]:
        """
        Run Docling's HybridChunker on the document.

        Emits warnings if chunker creates oversized chunks (token limit exceeded).

        Args:
            doc: DoclingDocument instance

        Returns:
            List of chunk objects from HybridChunker
        """
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "error", message=".*Token indices sequence length.*"
            )
            assert self._chunker is not None
            chunks = self._chunker.chunk(doc)

        return chunks

    def _warn_if_chunk_over_token_limit(self, chunk_text: str, chunk_idx: int) -> None:
        """Warn if chunk exceeds configured token limit."""
        if self._tokenizer is None:
            return
        token_count = len(self._tokenizer.encode(chunk_text, add_special_tokens=True))
        if token_count > self.max_tokens:
            logger.warning(
                "Chunk %s has %s tokens (max %s) - continuing anyway",
                chunk_idx,
                token_count,
                self.max_tokens,
            )

    def _link_table_images(
        self,
        table_items_with_refs: List[Tuple[Dict[str, Any], str]],
        table_index_map: Dict[str, Dict[str, Any]],
        table_images_meta: Dict[str, Any],
    ) -> None:
        """Attach table image metadata to table entries when available."""
        for table_dict, table_ref in table_items_with_refs:
            if table_ref not in table_index_map:
                continue

            table_info = table_index_map[table_ref]
            t_idx = table_info["idx"]

            table_dict["bbox"] = table_info.get("bbox")
            table_dict["page"] = table_info.get("page")
            table_dict["position_hint"] = table_info.get("position_hint")

            if str(t_idx) in table_images_meta:
                img_meta = table_images_meta[str(t_idx)]
                table_dict["image_path"] = img_meta.get("image_path")
                table_dict["image_size"] = img_meta.get("size")
                logger.debug(
                    "Linked table %s to image: %s", t_idx, img_meta.get("image_path")
                )
            else:
                logger.debug(
                    "No image found for table %s (available: %s)",
                    t_idx,
                    list(table_images_meta.keys()),
                )

    def _get_chunk_headings(self, chunk: Any) -> List[str]:
        """Extract headings from a chunk if available."""
        if hasattr(chunk, "meta") and hasattr(chunk.meta, "headings"):
            return chunk.meta.headings
        return []

    def _process_single_chunk(
        self,
        doc: DoclingDocument,
        chunk: Any,
        chunk_idx: int,
        text_map: Dict[str, str],
        fixed_text_map: Dict[str, str],
        table_index_map: Dict[str, Dict[str, Any]],
        images_by_page: Dict[int, List[Dict[str, Any]]],
        table_images_meta: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Process a single chunk: extract metadata, enrich with tables/images/text.

        This orchestrates the chunk processing pipeline:
        1. Extract basic metadata (pages, bboxes, item types)
        2. Extract table data if present
        3. Build unified chunk_elements array
        4. Add images with bbox filtering
        5. Assemble final chunk dictionary

        Args:
            doc: Full DoclingDocument
            chunk: Single chunk from HybridChunker
            chunk_idx: Index of this chunk
            text_map: Map of self_ref -> text
            table_index_map: Table metadata map
            images_by_page: Images metadata by page
            table_images_meta: Table image paths

        Returns:
            Dict with chunk data or None if processing fails
        """
        chunk_text = self._clean_text(chunk.text)

        # Validate token length (warn only - Docling may emit slightly oversized chunks)
        self._warn_if_chunk_over_token_limit(chunk_text, chunk_idx)

        # Extract basic metadata from chunk provenance
        metadata = self._extract_chunk_metadata(chunk, text_map, fixed_text_map)
        page_nums = metadata["page_nums"]
        bboxes = metadata["bboxes"]
        elements = metadata["elements"]

        self._clean_element_texts(elements)

        item_types = metadata["item_types"]
        tables_list = metadata["tables_list"]
        table_items_with_refs = metadata["table_items_with_refs"]

        # Link table images to tables that were properly associated
        self._link_table_images(
            table_items_with_refs, table_index_map, table_images_meta
        )

        # Get headings
        headings = self._get_chunk_headings(chunk)

        # Try to recover missing table associations (ad hoc heuristic)
        if "TableItem" not in item_types and not tables_list:
            self._maybe_recover_table(
                doc,
                chunk_text,
                table_index_map,
                table_images_meta,
                item_types,
                tables_list,
            )

        # Build unified chunk_elements array with all element types
        chunk_elements = self._build_chunk_elements(
            tables_list,
            elements,
            images_by_page,
            page_nums,
        )

        # Clean headings
        if not headings:
            headings = []
        headings = [self._clean_text(h) for h in headings]

        # Assemble final chunk dictionary
        return self._assemble_chunk_data(
            chunk_text,
            page_nums,
            chunk_elements,
            headings,
            item_types,
            bboxes,
            tables_list,
            elements,
            images_by_page,
        )

    def _clean_element_texts(self, elements: List[Dict[str, Any]]) -> None:
        for element in elements:
            if element.get("text"):
                cleaned = self._clean_text(element["text"])
                label = element.get("label", "")
                if label in ["footnote", "endnote"]:
                    cleaned = self._normalize_footnote_definition(cleaned)
                element["text"] = cleaned

    def _normalize_footnote_definition(self, text: str) -> str:
        """
        Normalize footnote definitions so the marker is consistent and inline
        with its content (e.g., "[^14] United Nations...").
        """
        if not text:
            return text
        match = re.match(
            r"^(?P<prefix>\s*)(?:"
            r"\[\^?(?P<num>\d{1,3})\]"
            r"|<sup>(?P<num2>\d{1,3})</sup>"
            r"|\^(?P<num3>\d{1,3})"
            r"|\((?P<num4>\d{1,3})\)"
            r"|(?P<num5>\d{1,3})"
            r")(?P<rest>[\s\S]*)$",
            text,
        )
        if not match:
            return text
        number = (
            match.group("num")
            or match.group("num2")
            or match.group("num3")
            or match.group("num4")
            or match.group("num5")
        )
        rest = match.group("rest") or ""
        if rest:
            rest = re.sub(r"^\s+", " ", rest)
        return f"{match.group('prefix')}[^{number}]{rest}"

    def _maybe_recover_table(
        self,
        doc: DoclingDocument,
        chunk_text: str,
        table_index_map: Dict[str, Dict[str, Any]],
        table_images_meta: Dict[str, Any],
        item_types: Set[str],
        tables_list: List[Dict[str, Any]],
    ) -> None:
        recovered_table = self._try_recover_missing_table(
            doc, chunk_text, table_index_map, table_images_meta
        )
        if recovered_table:
            item_types.add("TableItem")
            tables_list.append(recovered_table)

    def _assemble_chunk_data(
        self,
        chunk_text: str,
        page_nums: Set[int],
        chunk_elements: List[Dict[str, Any]],
        headings: List[str],
        item_types: Set[str],
        bboxes: List[Tuple[int, Tuple]],
        tables_list: List[Dict[str, Any]],
        elements: List[Dict[str, Any]],
        images_by_page: Dict[int, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        chunk_data = {
            "text": chunk_text,
            "page_num": min(page_nums) if page_nums else 1,
            "chunk_elements": chunk_elements,
            "headings": headings,
            "item_types": list(item_types),
        }
        chunk_data["bbox"] = [bbox for bbox in bboxes if bbox]
        if tables_list:
            chunk_data["tables"] = tables_list
            chunk_data["table_data"] = tables_list[0]
        chunk_images = self._extract_chunk_images(elements, images_by_page, page_nums)
        if chunk_images:
            chunk_data["images"] = chunk_images
        return chunk_data

    def _extract_chunk_metadata(
        self,
        chunk: Any,
        text_map: Dict[str, str],
        fixed_text_map: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Extract basic metadata from chunk provenance.

        Extracts:
        - Page numbers
        - Bounding boxes
        - Element metadata (text, type, label, bbox, position)
        - Item types
        - Tables data

        Args:
            chunk: Chunk object from HybridChunker
            text_map: Map of self_ref -> text for resolving text content

        Returns:
            Dict with 'page_nums', 'bboxes', 'elements', 'item_types', 'tables_list'
        """
        page_nums: Set[int] = set()
        bboxes: List[Tuple[int, Tuple]] = []
        elements: List[Dict[str, Any]] = []
        item_types: Set[str] = set()
        tables_list: List[Dict[str, Any]] = []
        # Track table items with their self_refs for image linking
        table_items_with_refs: List[Tuple[Any, str]] = []

        if hasattr(chunk, "meta") and hasattr(chunk.meta, "doc_items"):
            for item in chunk.meta.doc_items:
                item_type = type(item).__name__
                item_types.add(item_type)

                table_dict = self._extract_table_item(item_type, item)
                if table_dict:
                    if hasattr(item, "self_ref"):
                        table_items_with_refs.append((table_dict, item.self_ref))
                    tables_list.append(table_dict)

                if hasattr(item, "prov"):
                    self._extract_item_provenance(
                        item,
                        item_type,
                        text_map,
                        fixed_text_map,
                        page_nums,
                        bboxes,
                        elements,
                    )

        return {
            "page_nums": page_nums,
            "bboxes": bboxes,
            "elements": elements,
            "item_types": item_types,
            "tables_list": tables_list,
            "table_items_with_refs": table_items_with_refs,
        }

    def _extract_table_item(
        self, item_type: str, item: Any
    ) -> Optional[Dict[str, Any]]:
        if item_type == "TableItem" and hasattr(item, "data"):
            return self._extract_table_data(item)
        return None

    def _extract_item_provenance(
        self,
        item: Any,
        item_type: str,
        text_map: Dict[str, str],
        fixed_text_map: Optional[Dict[str, str]],
        page_nums: Set[int],
        bboxes: List[Tuple[int, Tuple]],
        elements: List[Dict[str, Any]],
    ) -> None:
        for prov in item.prov:
            page_nums.add(prov.page_no)
            if not (hasattr(prov, "bbox") and prov.bbox):
                continue
            bbox_tuple = prov.bbox.as_tuple()
            bboxes.append((prov.page_no, bbox_tuple))
            item_text = self._resolve_item_text(
                item, item_type, text_map, fixed_text_map
            )
            element_data = self._build_element_data(
                item, item_type, prov, bbox_tuple, item_text
            )
            elements.append(element_data)

    def _resolve_item_text(
        self,
        item: Any,
        item_type: str,
        text_map: Dict[str, str],
        fixed_text_map: Optional[Dict[str, str]],
    ) -> str:
        if item_type not in ["DocItem", "TextItem", "ListItem", "SectionHeaderItem"]:
            return ""
        item_ref = getattr(item, "self_ref", None)
        if fixed_text_map and item_ref and item_ref in fixed_text_map:
            return fixed_text_map[item_ref]
        if hasattr(item, "text") and item.text:
            item_text = item.text
            if isinstance(item, ListItem) and getattr(item, "marker", None):
                clean_marker = item.marker.strip()
                if clean_marker and not item_text.strip().startswith(clean_marker):
                    item_text = f"{item.marker} {item_text}"
            return item_text
        if item_ref:
            return text_map.get(item_ref, "")
        return ""

    def _build_element_data(
        self,
        item: Any,
        item_type: str,
        prov: Any,
        bbox_tuple: Tuple,
        item_text: str,
    ) -> Dict[str, Any]:
        position_from_top = PAGE_HEIGHT - bbox_tuple[3]
        return {
            "type": item_type,
            "label": getattr(item, "label", "text"),
            "text": item_text,
            "page": prov.page_no,
            "bbox": list(bbox_tuple),
            "position_hint": round(position_from_top / PAGE_HEIGHT, 3),
        }

    def _extract_table_data(self, item: Any) -> Optional[Dict[str, Any]]:
        """
        Extract simplified table structure from a TableItem.

        Extracts:
        - Grid structure with cells
        - Cell text, header status, row/col spans
        - Dimensions (num_rows, num_cols)

        Args:
            item: TableItem from Docling

        Returns:
            Dict with table structure or None if extraction fails
        """
        try:
            data = item.data
            table_rows = self._build_table_rows(data)
            if table_rows:
                return {
                    "num_rows": getattr(data, "num_rows", len(table_rows)),
                    "num_cols": getattr(data, "num_cols", 0),
                    "rows": table_rows[:50],
                }
        except Exception:
            pass

        return None

    def _build_table_rows(self, data: Any) -> List[List[Dict[str, Any]]]:
        table_rows = []
        if hasattr(data, "grid") and data.grid:
            for row in data.grid:
                row_cells = self._build_table_row_cells(row)
                if row_cells:
                    table_rows.append(row_cells)
        return table_rows

    def _build_table_row_cells(self, row: Any) -> List[Dict[str, Any]]:
        row_cells = []
        seen_texts = set()
        for cell in row:
            if not hasattr(cell, "text") or cell.text in seen_texts:
                continue
            seen_texts.add(cell.text)
            row_cells.append(
                {
                    "text": cell.text,
                    "is_header": getattr(cell, "column_header", False)
                    or getattr(cell, "row_header", False),
                    "row_span": getattr(cell, "row_span", 1),
                    "col_span": getattr(cell, "col_span", 1),
                }
            )
        return row_cells

    def _try_recover_missing_table(
        self,
        doc: DoclingDocument,
        chunk_text: str,
        table_index_map: Dict[str, Dict[str, Any]],
        table_images_meta: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Try to recover table association when Docling's chunker misses it.

        AD HOC HEURISTIC: If chunk text contains cells from a known table,
        extract and return that table's data.

        This handles cases where Docling's chunker doesn't associate TableItem
        with a chunk that contains table text.

        Args:
            doc: Full DoclingDocument
            chunk_text: Text content of current chunk
            table_index_map: Map of table refs to metadata
            table_images_meta: Table image paths

        Returns:
            Table dict if recovered, None otherwise
        """
        for table_ref, table_info in table_index_map.items():
            table_item = self._find_table_item(doc, table_ref)
            if not table_item or not self._table_matches_chunk(table_item, chunk_text):
                continue
            table_data = self._extract_table_data(table_item)
            if table_data:
                return self._decorate_table_data(
                    table_data, table_info, table_images_meta
                )

        return None

    def _find_table_item(self, doc: DoclingDocument, table_ref: str) -> Any:
        for item, _ in doc.iterate_items():
            if (
                type(item).__name__ == "TableItem"
                and hasattr(item, "self_ref")
                and item.self_ref == table_ref
            ):
                return item
        return None

    def _table_matches_chunk(self, table_item: Any, chunk_text: str) -> bool:
        if not (hasattr(table_item, "data") and hasattr(table_item.data, "grid")):
            return False
        matches = self._count_table_matches(table_item.data.grid, chunk_text)
        return matches >= 2

    def _count_table_matches(self, grid: Any, chunk_text: str) -> int:
        matches = 0
        for row in grid[:5]:
            for cell in row[:3]:
                if hasattr(cell, "text") and cell.text and len(cell.text) > 3:
                    if cell.text in chunk_text:
                        matches += 1
                        if matches >= 2:
                            return matches
        return matches

    def _decorate_table_data(
        self,
        table_data: Dict[str, Any],
        table_info: Dict[str, Any],
        table_images_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        table_data["bbox"] = table_info.get("bbox")
        table_data["page"] = table_info.get("page")
        table_data["position_hint"] = table_info.get("position_hint")
        t_idx = table_info.get("idx")
        if t_idx is not None and str(t_idx) in table_images_meta:
            img_meta = table_images_meta[str(t_idx)]
            table_data["image_path"] = img_meta.get("image_path")
            table_data["image_size"] = img_meta.get("size")
        return table_data

    def _build_chunk_elements(
        self,
        tables_list: List[Dict[str, Any]],
        elements: List[Dict[str, Any]],
        images_by_page: Dict[int, List[Dict[str, Any]]],
        page_nums: Set[int],
    ) -> List[Dict[str, Any]]:
        """
        Build unified chunk_elements array with text, images, and tables.

        Combines all element types into a single sorted array:
        1. Add tables (even if no text elements - handles pure table chunks)
        2. Add text elements with reference detection
        3. Add images with bbox overlap filtering
        4. Sort by page and position
        5. Filter out images before first non-caption text

        Args:
            tables_list: List of table dicts
            elements: List of text element dicts
            images_by_page: Images metadata by page
            page_nums: Set of page numbers in chunk

        Returns:
            List of chunk elements sorted by position
        """
        chunk_elements = self._build_table_elements(tables_list, page_nums)
        chunk_elements.extend(self._build_text_elements(elements))

        # Add images with bbox filtering
        self._add_images_to_chunk_elements(
            chunk_elements, elements, images_by_page, page_nums
        )

        # Sort all elements by page, then position_hint
        chunk_elements.sort(key=lambda x: (x.get("page", 0), x.get("position_hint", 0)))

        # Filter out images before first non-caption text
        chunk_elements = self._filter_images_before_text(chunk_elements)

        # Filter out Excel/table metadata text (e.g., "Best match (score X): [Sheet: Y]")
        chunk_elements = self._filter_table_metadata_text(chunk_elements)

        return chunk_elements

    def _build_table_elements(
        self, tables_list: List[Dict[str, Any]], page_nums: Set[int]
    ) -> List[Dict[str, Any]]:
        elements = []
        fallback_page = min(page_nums) if page_nums else 1
        for table in tables_list:
            elements.append(
                {
                    "element_type": "table",
                    "num_rows": table.get("num_rows"),
                    "num_cols": table.get("num_cols"),
                    "rows": table.get("rows"),
                    "image_path": table.get("image_path"),
                    "image_size": table.get("image_size"),
                    "bbox": table.get("bbox"),
                    "page": table.get("page", fallback_page),
                    "position_hint": table.get("position_hint", 0),
                }
            )
        return elements

    def _build_text_elements(
        self, elements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        text_elements = []
        for elem in elements:
            if not elem.get("text"):
                continue
            text = elem.get("text", "")
            label = elem.get("label", "text")
            is_reference = self._is_reference_element(text, label)
            text_elements.append(
                {
                    "element_type": "text",
                    "label": label,
                    "text": text,
                    "is_reference": is_reference,
                    "page": elem.get("page"),
                    "bbox": elem.get("bbox"),
                    "position_hint": elem.get("position_hint"),
                }
            )
        return text_elements

    def _is_reference_element(self, text: str, label: str) -> bool:
        """
        Detect if text element is a reference (footnote/endnote with leading number).

        Args:
            text: Text content
            label: Element label (e.g., 'footnote', 'endnote')

        Returns:
            True if element is a reference, False otherwise
        """
        if label in ["footnote", "endnote"]:
            text_stripped = text.strip()
            # Handle standard "123", geometric "^123", or HTML "<sup>123</sup>"
            if not text_stripped:
                return False

            # Check for leading digits or leading markers
            if text_stripped[0].isdigit():
                return True
            elif (
                text_stripped.startswith("^")
                and len(text_stripped) > 1
                and text_stripped[1].isdigit()
            ):
                return True
            elif text_stripped.startswith("["):
                # Handle [123] or [^123]
                # Look for digit inside brackets near start
                match = re.search(r"^\[\^?(\d+)", text_stripped)
                return bool(match)
            elif text_stripped.startswith("<sup>") and "</sup>" in text_stripped:
                # Check if content inside tags is digits
                match = re.match(r"^<sup>(\d+)</sup>", text_stripped)
                return bool(match)

        return False

    def _clean_text(self, text: str) -> str:
        """
        Clean text to remove artifacts like replacement characters and excessive spacing.

        Fixes:
        1. Unicode replacement char \ufffd -> 'ti' (common ligature replacement)
           - e.g., "Harmonisa\ufffdon" -> "Harmonisation"
           - e.g., "Mee\ufffdng" -> "Meeting"
           - e.g., "D\ufffdmocra\ufffdque" -> "Démocratique" (handle 'D\ufffdmo' -> 'Démo')
        2. Spaced text -> Collapsed text
           - e.g., "D a t a   s o u r c e s" -> "Data sources"

        Args:
            text: Raw text string

        Returns:
            Cleaned text string
        """
        if not text:
            return text

        cleaned = self._fix_unicode_replacements(text)
        cleaned = self._standardize_footnotes(cleaned)
        cleaned = self._collapse_spaced_text(cleaned)
        return cleaned

    def _fix_unicode_replacements(self, text: str) -> str:
        cleaned = text
        if "\ufffd" in cleaned:
            cleaned = cleaned.replace("D\ufffdmo", "Démo")
            cleaned = cleaned.replace("R\ufffdpublique", "République")
            cleaned = cleaned.replace("cr\ufffdque", "cratique")
            cleaned = cleaned.replace("\ufffd", "ti")
        if "\uf0b7" in cleaned:
            cleaned = cleaned.replace("\uf0b7", "•")
        return cleaned

    def _standardize_footnotes(self, text: str) -> str:
        cleaned = re.sub(r"\[(\d{1,3})\]", r"[^\1]", text)
        cleaned = re.sub(r"\^(\d{1,3})", r"[^\1]", cleaned)
        return re.sub(r"(^|\n)\[\^(\d{1,3})\](?!\:)", r"\1[^\2]:", cleaned)

    def _collapse_spaced_text(self, text: str) -> str:
        spaced_text_pattern = r"\b(?:[a-zA-Z]\s+){3,}[a-zA-Z]\b"

        def collapse_spaces(match):
            chunk = match.group(0)
            if "   " in chunk:
                parts = chunk.split("   ")
                return " ".join([part.replace(" ", "") for part in parts])
            return chunk.replace(" ", "")

        if re.search(spaced_text_pattern, text):
            return re.sub(spaced_text_pattern, collapse_spaces, text)
        return text

    def _add_images_to_chunk_elements(
        self,
        chunk_elements: List[Dict[str, Any]],
        elements: List[Dict[str, Any]],
        images_by_page: Dict[int, List[Dict[str, Any]]],
        page_nums: Set[int],
    ) -> None:
        """
        Add images to chunk_elements with bbox overlap filtering.


        Only includes images whose bboxes overlap with text element bboxes.
        Applies tolerance for chunks with caption keywords (figure/table/diagram).

        Modifies chunk_elements in place.

        Args:
            chunk_elements: List to add images to (modified in place)
            elements: Text elements with bboxes
            images_by_page: Images metadata by page
            page_nums: Set of page numbers in chunk
        """
        add_images_to_chunk_elements(
            chunk_elements, elements, images_by_page, page_nums
        )

    def _calculate_text_bbox_ranges(
        self, elements: List[Dict[str, Any]]
    ) -> Dict[int, Dict[str, float]]:
        """
        Calculate Y-coordinate bbox ranges from text elements by page.

        Used for image overlap filtering - only images within text bbox range
        are included (with optional tolerance).

        Args:
            elements: List of text element dicts with bbox and page

        Returns:
            Dict mapping page -> {'min_y', 'max_y'} in PDF coordinates
        """
        return calculate_text_bbox_ranges(elements)

    def _should_include_image(
        self,
        img_bbox: List[float],
        text_range: Dict[str, float],
        has_caption_keywords: bool,
    ) -> bool:
        """
        Determine if image should be included based on bbox overlap with text.

        Uses strict overlap by default. If chunk has caption keywords
        (figure/table/diagram), applies tolerance of 250 points.

        Args:
            img_bbox: Image bounding box [left, min_y, right, max_y]
            text_range: Text bbox range {'min_y', 'max_y'}
            has_caption_keywords: True if chunk has figure/table/diagram captions

        Returns:
            True if image should be included, False otherwise
        """
        return should_include_image(img_bbox, text_range, has_caption_keywords)

    def _filter_images_before_text(
        self, chunk_elements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter out images that appear BEFORE the first text element.

        Exception: If first text is a caption or starts with figure keywords,
        keep preceding images (they're likely referenced by the caption).

        Args:
            chunk_elements: List of chunk elements sorted by position

        Returns:
            Filtered list of chunk elements
        """
        return filter_images_before_text(chunk_elements)

    def _filter_table_metadata_text(
        self, chunk_elements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter out Excel/table extraction metadata text that shouldn't be displayed.

        Removes text elements that look like table extraction metadata,
        such as "Best match (score 71): [Sheet: Unemployment]" or similar
        provenance text that appears before table images.

        Args:
            chunk_elements: List of chunk elements

        Returns:
            Filtered list without table metadata text
        """
        return filter_table_metadata_text(chunk_elements)

    def _extract_chunk_images(
        self,
        elements: List[Dict[str, Any]],
        images_by_page: Dict[int, List[Dict[str, Any]]],
        page_nums: Set[int],
    ) -> List[Dict[str, Any]]:
        """
        Extract images list for backward compatibility.

        Filters images by bbox overlap with conditional tolerance,
        same logic as _add_images_to_chunk_elements.

        Args:
            elements: Text elements with bboxes
            images_by_page: Images metadata by page
            page_nums: Set of page numbers in chunk

        Returns:
            List of image dicts that should be associated with chunk
        """
        return extract_chunk_images(elements, images_by_page, page_nums)
