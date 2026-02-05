"""Pipeline processor for tagger implementations."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastembed import TextEmbedding
from qdrant_client import models

from pipeline.db import Database, PostgresClient, make_stage, update_stages
from pipeline.processors.base import BaseProcessor
from pipeline.processors.tagging.tagger_base import BaseTagger
from pipeline.processors.tagging.tagger_section_type import SectionTypeTagger
from pipeline.processors.tagging.tagger_taxonomy import TaxonomyTagger

logger = logging.getLogger(__name__)


class TaggerProcessor(BaseProcessor):
    """
    Pipeline processor that applies semantic tags to chunks.

    Architecture:
    - process_document() iterates chunks for one document
    - for each chunk, calls tag_chunk() on each registered tagger
    - each tagger independently determines its tag value
    """

    name = "TaggerProcessor"
    stage_name = "tag"

    def __init__(self, data_source: str = "uneg", config: Dict[str, Any] = None):
        super().__init__()
        self.data_source = data_source
        self.config = config or {}
        self._database: Optional[Database] = None
        self._pg: Optional[PostgresClient] = None
        self._embedding_model: Optional[TextEmbedding] = None
        self._taggers: List[BaseTagger] = []

        # Strict Config for Model
        self.dense_model_name = self.config.get("dense_model")
        # If not provided, we might fail or default if user allows fallback?
        # User said "NO Fallback... process should fail".
        # But if Tagger is used CLI-style, config might be absent?
        # For now, we enforce config usage in pipeline.

    def setup(self, embedding_model: Optional[TextEmbedding] = None) -> None:
        """Load embedding model and initialize taggers."""
        if embedding_model is not None:
            logger.info("Using shared embedding model")
            self._embedding_model = embedding_model
        else:
            if not self.dense_model_name:
                raise ValueError("TaggerProcessor: 'dense_model' missing in config")

            logger.info("Loading embedding model: %s", self.dense_model_name)
            self._embedding_model = TextEmbedding(model_name=self.dense_model_name)

        self._database = Database(data_source=self.data_source)
        self._pg = PostgresClient(self.data_source)
        self._init_taggers()

        for tagger in self._taggers:
            tagger.setup()

        logger.info(
            "Initialized %d taggers: %s",
            len(self._taggers),
            [tagger.name for tagger in self._taggers],
        )
        super().setup()

    def _init_taggers(self) -> None:
        assert self._embedding_model is not None
        assert self._database is not None

        section_type_tagger = SectionTypeTagger(
            self._embedding_model, llm_config=self.config
        )
        section_type_tagger.set_db(self._database)

        taxonomy_tagger = TaxonomyTagger(self._embedding_model, config=self.config)
        taxonomy_tagger.set_db(self._database)

        self._taggers = [
            section_type_tagger,
            taxonomy_tagger,
        ]

    def teardown(self) -> None:
        self._embedding_model = None
        self._taggers = []
        super().teardown()

    def process_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all taggers to chunks of a document."""
        self.ensure_setup()
        assert self._database is not None

        doc_id = doc.get("id") or doc.get("node_id")
        chunks = self._get_document_chunks(doc_id)

        if not chunks:
            return {"success": True, "skipped": True, "reason": "No chunks found"}

        logger.info("Tagging %d chunks for doc %s", len(chunks), doc_id)

        updates_count = 0
        for chunk_id, chunk_payload in chunks:
            updates = self._tag_single_chunk(chunk_payload, doc)
            if updates:
                self._update_chunk(chunk_id, updates)
                updates_count += 1

        logger.info(
            "Updated %d/%d chunks for doc %s", updates_count, len(chunks), doc_id
        )

        if self._pg is not None:
            self._update_document_tags(doc, doc_id)

        return {
            "success": True,
            "chunks_processed": len(chunks),
            "chunks_updated": updates_count,
        }

    def _apply_taxonomy_tags(self, doc: Dict[str, Any], doc_id: str) -> None:
        """Run taxonomy tagger and save results."""
        try:
            taxonomy_tagger = next(
                (t for t in self._taggers if isinstance(t, TaxonomyTagger)), None
            )
            if taxonomy_tagger:
                doc_tags = taxonomy_tagger.compute_document_tags(doc)
                if doc_tags:
                    # 1. Save to Postgres
                    if "sys_taxonomies" in doc_tags:
                        self._pg.merge_doc_sys_fields(
                            doc_id=str(doc_id),
                            sys_fields={},
                            sys_taxonomies=doc_tags["sys_taxonomies"],
                        )
                    # 2. Save to Qdrant
                    self._update_qdrant_payload(doc_id, doc_tags)
                    logger.info("Saved taxonomy tags for doc %s", doc_id)
        except Exception as exc:
            logger.error("Failed to apply taxonomy tags for doc %s: %s", doc_id, exc)

    def _update_document_tags(self, doc: Dict[str, Any], doc_id: str) -> None:
        """Compute tags and set status."""
        self._apply_taxonomy_tags(doc, doc_id)
        try:
            self._pg.merge_doc_sys_fields(
                doc_id=str(doc_id), sys_fields={"sys_status": "tagged"}
            )
            logger.info("Set status to 'tagged' for doc %s", doc_id)
        except Exception as exc:
            logger.error("Failed to update status for doc %s: %s", doc_id, exc)

    def _update_qdrant_payload(self, doc_id: str, doc_tags: Dict[str, Any]) -> None:
        """Update Qdrant payload with taxonomy tags."""
        qdrant_updates = {k: v for k, v in doc_tags.items() if k.startswith("tag_")}

        if qdrant_updates:
            try:
                self._database.client.set_payload(
                    collection_name=self._database.documents_collection,
                    payload=qdrant_updates,
                    points=[(int(doc_id) if str(doc_id).isdigit() else str(doc_id))],
                )
                logger.info("Updated Qdrant payload for doc %s", doc_id)
            except Exception as exc:
                logger.warning(
                    "Failed to update Qdrant payload for doc %s: %s", doc_id, exc
                )

    def classify_toc_only(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify document TOC without tagging chunks.
        Sets status to 'tagged' after TOC classification.
        """
        self.ensure_setup()
        assert self._database is not None

        doc_id = doc.get("id") or doc.get("node_id")

        section_type_tagger: Optional[SectionTypeTagger] = None
        for tagger in self._taggers:
            if isinstance(tagger, SectionTypeTagger):
                section_type_tagger = tagger
                break

        if section_type_tagger is None:
            return {"success": False, "error": "SectionTypeTagger not found"}

        classifications = section_type_tagger.classify_document_toc(doc)

        stage_info = make_stage(
            success=True, sections_count=len(classifications) if classifications else 0
        )
        existing_stages = self._get_existing_stages(doc)
        updated_stages = update_stages(existing_stages, "tag", stage_info)

        # Taxonomy Tagging
        if self._pg is not None:
            self._apply_taxonomy_tags(doc, doc_id)

        if self._pg is not None:
            try:
                sys_fields_update = {
                    "sys_status": "tagged",
                    "sys_stages": updated_stages,
                }

                self._pg.merge_doc_sys_fields(
                    doc_id=str(doc_id),
                    sys_fields=sys_fields_update,
                )
                logger.info("Set status to 'tagged' for doc %s", doc_id)
            except Exception as exc:
                logger.error("Failed to update status for doc %s: %s", doc_id, exc)
                return {"success": False, "error": str(exc)}

        return {
            "success": True,
            "toc_classified": bool(classifications),
            "sections_count": len(classifications) if classifications else 0,
        }

    def tag_chunks_only(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Tag chunks with section_type without updating document status."""
        self.ensure_setup()
        assert self._database is not None

        doc_id = doc.get("id") or doc.get("node_id")
        chunks = self._get_document_chunks(doc_id)

        if not chunks:
            return {"success": True, "skipped": True, "reason": "No chunks found"}

        updates_count = 0
        for chunk_id, chunk_payload in chunks:
            updates = self._tag_single_chunk(chunk_payload, doc)
            if updates:
                self._update_chunk(chunk_id, updates)
                updates_count += 1

        logger.info(
            "Tagged %d/%d chunks for doc %s", updates_count, len(chunks), doc_id
        )
        return {
            "success": True,
            "chunks_processed": len(chunks),
            "chunks_updated": updates_count,
        }

    def _tag_single_chunk(
        self, chunk: Dict[str, Any], doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply all taggers to a single chunk payload."""
        updates: Dict[str, Any] = {}

        for tagger in self._taggers:
            tag_value = tagger.tag_chunk(chunk, doc)
            if tag_value is not None:
                if isinstance(tag_value, dict):
                    # Tagger returned multiple fields (e.g. TaxonomyTagger)
                    updates.update(tag_value)
                else:
                    current_value = chunk.get(tagger.tag_field)
                    if current_value != tag_value:
                        updates[tagger.tag_field] = tag_value

        return updates

    def _get_document_chunks(self, doc_id: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Get all chunks for a document."""
        assert self._database is not None

        chunks: List[Tuple[str, Dict[str, Any]]] = []
        offset = None

        while True:
            results, offset = self._database.client.scroll(
                collection_name=self._database.chunks_collection,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchValue(value=doc_id),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=True,
            )

            for point in results:
                chunks.append((str(point.id), point.payload))

            if offset is None:
                break

        if not chunks or self._pg is None:
            return chunks

        chunk_payloads = {chunk_id: payload for chunk_id, payload in chunks}
        sidecar_chunks = self._pg.fetch_chunks(chunk_payloads.keys())
        for chunk_id, payload in chunk_payloads.items():
            sidecar_payload = sidecar_chunks.get(str(chunk_id), {})
            payload.update(
                {
                    "sys_page_num": sidecar_payload.get("sys_page_num"),
                    "sys_headings": sidecar_payload.get("sys_headings"),
                }
            )

        return [(chunk_id, chunk_payloads[chunk_id]) for chunk_id, _ in chunks]

    def _update_chunk(self, chunk_id: str, updates: Dict[str, Any]) -> None:
        """Update chunk payload in Qdrant."""
        assert self._database is not None
        self._database.client.set_payload(
            collection_name=self._database.chunks_collection,
            payload=updates,
            points=[chunk_id],
        )

        # Update Postgres sidecar
        if self._pg is not None:
            # We need to extract what fields to update.
            # _update_chunk is generic, but merge_chunk_sys_fields expects specific Args
            # or we pass everything as sys_fields?
            # merge_chunk_sys_fields args: tag_section_type, sys_taxonomies, sys_fields

            tag_section_type = updates.get("tag_section_type")
            sys_taxonomies = updates.get("sys_taxonomies")

            # Remaining updates go to sys_fields (excluding known columns if any)
            # Actually, updates contains EVERYTHING that changed.
            # We filter out what is handled explicitly.

            pg_updates = {
                k: v
                for k, v in updates.items()
                if k not in ["tag_section_type", "sys_taxonomies"]
            }

            if tag_section_type or sys_taxonomies or pg_updates:
                try:
                    self._pg.merge_chunk_sys_fields(
                        chunk_id=chunk_id,
                        sys_fields=pg_updates,
                        tag_section_type=tag_section_type,
                        sys_taxonomies=sys_taxonomies,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to update Postgres chunk %s: %s", chunk_id, exc
                    )

    def process_all_documents(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Process all indexed documents."""
        self.ensure_setup()
        assert self._database is not None

        documents_processed = 0
        documents_skipped = 0
        total_chunks_updated = 0

        offset = None
        while True:
            results, offset = self._database.client.scroll(
                collection_name=self._database.documents_collection,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="sys_status",
                            match=models.MatchValue(value="indexed"),
                        )
                    ]
                ),
                limit=50,
                offset=offset,
                with_payload=True,
            )

            for point in results:
                if limit and documents_processed >= limit:
                    break

                doc = point.payload
                doc["id"] = str(point.id)

                result = self.process_document(doc)

                if result.get("skipped"):
                    documents_skipped += 1
                else:
                    documents_processed += 1
                    total_chunks_updated += result.get("chunks_updated", 0)

            if offset is None or (limit and documents_processed >= limit):
                break

        return {
            "documents_processed": documents_processed,
            "documents_skipped": documents_skipped,
            "total_chunks_updated": total_chunks_updated,
        }
