"""
indexer.py - Document indexing processor for Qdrant.

Loads embedding models once during setup() and indexes documents
into the chunks collection with document metadata denormalized.
Includes document chunking using Docling's HybridChunker.
"""

import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from dotenv import load_dotenv
from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client.http import models
from transformers import AutoTokenizer

from pipeline.db import (
    DB_VECTORS,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    Database,
    PostgresClient,
    get_db,
)
from pipeline.processors.base import BaseProcessor
from pipeline.processors.indexing.chunker import Chunker
from pipeline.utilities.azure_client import AzureEmbeddingClient

load_dotenv()

logger = logging.getLogger(__name__)


# Load configuration from environment
# Helper for E5 model detection
def is_e5_model(model_name: str) -> bool:
    """Return True when the model name indicates an E5 embedding model."""
    return "e5" in str(model_name).lower()


def add_passage_prefix(text: str, model_name: str) -> str:
    """Add 'passage: ' prefix for E5 models during indexing."""
    if is_e5_model(model_name):
        return f"passage: {text}"
    return text


def year_to_unix(year_str: Optional[str]) -> Optional[int]:
    """
    Convert a year string to Unix timestamp (Jan 1 of that year, UTC).

    Args:
        year_str: Year as string (e.g., "2024") or None

    Returns:
        Unix timestamp in seconds, or None if invalid
    """
    if not year_str:
        return None
    try:
        year = int(year_str)
        # Create datetime for Jan 1 of that year, midnight UTC
        dt = datetime(year, 1, 1, 0, 0, 0)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


class IndexProcessor(BaseProcessor):
    """
    Document indexing processor for Qdrant.

    Creates:
    - Chunk embeddings (dense + sparse) with document metadata
    - Document-level embeddings from title + summary

    Includes document chunking using Docling's HybridChunker.
    """

    name = "IndexProcessor"
    stage_name = "index"

    def __init__(
        self,
        db: Database = None,
        index_config: Dict[str, Any] = None,
        chunk_config: Dict[str, Any] = None,
    ):
        """
        Initialize indexer configuration.

        Args:
            db: Database instance
            index_config: Indexing configuration (models, workers, batch size)
            chunk_config: Chunking configuration (max tokens, dense model ID)
        """
        super().__init__()
        self.db = db or get_db()
        self.pg = PostgresClient(self.db.data_source)
        self.index_config = index_config or {}
        self.chunk_config = chunk_config or {}

        # Strict Config Parsing
        self.max_chunk_tokens = self.chunk_config.get("max_tokens", 512)
        self.min_sub_size = self.chunk_config.get("min_substantive_size", 100)
        self.dense_model_id = self.chunk_config.get("dense_model")

        if not self.dense_model_id:
            # Fallback to defaults? User said strict valid.
            # If chunk config is missing, default to 512/100 is safe.
            # But dense_model_id is critical.
            pass

        self.batch_size = self.index_config.get("batch_size", 10)
        self.embedding_workers = self.index_config.get("embedding_workers", 4)

        self._dense_model = None
        self._sparse_model = None
        self._tokenizer = None
        self._chunker_instance: Optional[Chunker] = None

    def setup(self, dense_model=None) -> None:
        """Load configuration and embedding models (slow - done once)."""
        logger.info("Initializing %s...", self.name)

        # Initialize dictionary to hold all dense models
        self._dense_models: Dict[str, Any] = {}

        # Helper mapping for model lookup
        self._dense_model_map: Dict[str, Any] = {}

        targets = self.index_config.get("dense_models", [])
        self._load_dense_models(targets, dense_model)
        self._primary_dense_model = self._select_primary_dense_model()
        self._load_sparse_model()
        self._init_tokenizer_and_chunker()

        logger.info("✓ %s Embedding models and chunker loaded", len(self._dense_models))
        super().setup()

    def _load_dense_models(self, targets: List[str], dense_model: Any) -> None:
        for vec_name in targets:
            vec_config = DB_VECTORS.get(vec_name)
            if not vec_config:
                logger.warning(
                    "Model %s in config but not in DB_VECTORS registry", vec_name
                )
                continue
            self._dense_models[vec_name] = self._load_dense_model(
                vec_name, vec_config, dense_model
            )

    def _load_dense_model(
        self, vec_name: str, vec_config: Dict[str, Any], dense_model: Any
    ) -> Any:
        model_id = vec_config["model_id"]
        source = vec_config.get("source", "huggingface")
        logger.info(
            "Loading dense model '%s' (source: %s, model: %s)...",
            vec_name,
            source,
            model_id,
        )
        try:
            if source == "azure_foundry":
                api_key = os.getenv("AZURE_FOUNDRY_KEY")
                endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
                if not api_key or not endpoint:
                    raise ValueError(
                        f"Missing AZURE_FOUNDRY_KEY or AZURE_FOUNDRY_ENDPOINT for {vec_name}"
                    )
                return AzureEmbeddingClient(
                    api_key=api_key,
                    endpoint=endpoint,
                    deployment_name=str(model_id),
                )
            if dense_model and self.dense_model_id == model_id:
                logger.info("Using shared dense model instance for %s", vec_name)
                return dense_model
            return TextEmbedding(model_name=model_id)
        except Exception as exc:
            logger.error("Failed to load model %s: %s", vec_name, exc)
            raise

    def _select_primary_dense_model(self) -> Any:
        primary_model_name = DENSE_VECTOR_NAME
        if primary_model_name not in self._dense_models:
            if self._dense_models:
                primary_model_name = list(self._dense_models.keys())[0]
                logger.warning(
                    "Primary vector %s not found, using %s",
                    DENSE_VECTOR_NAME,
                    primary_model_name,
                )
            else:
                raise ValueError("No dense models loaded!")
        return self._dense_models[primary_model_name]

    def _load_sparse_model(self) -> None:
        sparse_models = self.index_config.get("sparse_models", ["bm25"])
        if not sparse_models:
            return
        s_name = sparse_models[0]
        s_cfg = DB_VECTORS.get(s_name)
        s_id = s_cfg["model_id"] if s_cfg else "Qdrant/bm25"
        logger.info("Loading sparse model: %s...", s_id)
        self._sparse_model = SparseTextEmbedding(model_name=s_id)

    def _init_tokenizer_and_chunker(self) -> None:
        if not self.dense_model_id:
            raise ValueError("Indexer: 'dense_model' missing in chunk config")
        self._tokenizer = AutoTokenizer.from_pretrained(self.dense_model_id)
        hybrid_chunker = HybridChunker(
            tokenizer=self.dense_model_id,
            max_tokens=self.max_chunk_tokens,
            merge_peers=True,
        )
        self._chunker_instance = Chunker(
            tokenizer=self._tokenizer, chunker=hybrid_chunker
        )

    def _chunk_document(self, json_path: str) -> List[Dict[str, Any]]:
        """
        Load a Docling JSON document and split into chunks.

        Delegates to Chunker class for all chunking logic.

        Args:
            json_path: Path to the Docling JSON file.

        Returns:
            List of chunk dictionaries with text, page_num, bbox, headings.
        """
        assert self._chunker_instance is not None, "Chunker not initialized"
        return self._chunker_instance.chunk_document(json_path)

    def _post_process_chunks(
        self, _doc: DoclingDocument, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Post-process chunks (deprecated - now handled by Chunker).

        This method is kept for backward compatibility but delegates to Chunker.

        Args:
            doc: The full DoclingDocument
            chunks: List of chunk dictionaries

        Returns:
            List of chunks with enhanced metadata
        """
        # Chunker already handles post-processing, so just return chunks
        return chunks

    def _build_failure(
        self, doc: Dict[str, Any], message: str, error: str
    ) -> Dict[str, Any]:
        stage_updates = self.build_stage_updates(doc, success=False, error=message)
        return {
            "success": False,
            "updates": {
                "sys_status": "index_failed",
                "sys_error_message": message,
                **stage_updates,
            },
            "error": error,
        }

    def _normalize_parsed_folder(self, parsed_folder: str) -> str:
        data_mount_path = os.getenv("DATA_MOUNT_PATH", "./data")
        logger.debug(
            "DEBUG_INDEXER: parsed_folder='%s', data_mount_path='%s'",
            parsed_folder,
            data_mount_path,
        )
        if parsed_folder.startswith("data/"):
            logger.debug("DEBUG_INDEXER: Branch 'data/' taken")
            return data_mount_path + "/" + parsed_folder[5:]
        if not parsed_folder.startswith("/") and not parsed_folder.startswith("./"):
            logger.debug("DEBUG_INDEXER: Branch './' taken")
            return "./" + parsed_folder
        return parsed_folder

    def _resolve_json_path(self, parsed_folder: str) -> Path:
        return Path(parsed_folder) / f"{Path(parsed_folder).name}.json"

    def _save_chunks_file(
        self, parsed_folder: str, chunks: List[Dict[str, Any]]
    ) -> None:
        try:
            chunks_dir = Path(parsed_folder) / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunks_file = chunks_dir / "chunks.json"
            with open(chunks_file, "w", encoding="utf-8") as f:
                json.dump(chunks, f, indent=2, default=str)
            logger.info("Saved chunks to %s", chunks_file)
        except Exception as e:
            logger.warning("Failed to save chunks to file: %s", e)

    def _filter_valid_chunks(
        self, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        valid_chunks = [c for c in chunks if c.get("text", "").strip()]
        if len(valid_chunks) < len(chunks):
            logger.warning(
                "Filtered out %s empty chunks.", len(chunks) - len(valid_chunks)
            )
        return valid_chunks

    def _build_batches(
        self, texts: List[str], dense_texts: List[str]
    ) -> List[Tuple[int, List[str], List[str], int]]:
        batches = []
        for i in range(0, len(texts), self.batch_size):
            batch_text = texts[i : i + self.batch_size]
            batch_dense = dense_texts[i : i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            batches.append((batch_num, batch_text, batch_dense, i))
        return batches

    def _embed_batch(
        self, batch_info: Tuple[int, List[str], List[str], int], total_batches: int
    ) -> Tuple[int, Dict[str, List[Any]], List[Any], int]:
        b_num, b_text, b_dense, start_idx = batch_info
        logger.info(
            "    Indexing Batch %s/%s (%s chunks)", b_num, total_batches, len(b_text)
        )
        assert self._sparse_model is not None

        embeddings_by_model: Dict[str, List[Any]] = {}
        for name, model in self._dense_models.items():
            if b_num == 1 and hasattr(model, "base_url"):
                logger.info("    🚀 Sending batch 1 to Azure for vector '%s'", name)
            is_azure = hasattr(model, "base_url")
            input_batch = b_text if is_azure else b_dense
            embeddings_by_model[name] = list(model.embed(input_batch))

        sparse_res = list(self._sparse_model.embed(b_text))
        return b_num, embeddings_by_model, sparse_res, start_idx

    def _build_doc_payload_fields(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        payload_fields: Dict[str, Any] = {}
        for key, value in doc.items():
            if value is None:
                continue
            if key.startswith(("src_", "map_", "tag_")):
                payload_fields[key] = value
        sys_language = doc.get("sys_language")
        if sys_language:
            payload_fields["sys_language"] = sys_language
        return payload_fields

    def _build_vectors_dict(
        self, embeddings_map: Dict[str, List[Any]], sparse_vec: Any, index: int
    ) -> Dict[str, Any]:
        vectors_dict = {
            name: vecs[index].tolist() for name, vecs in embeddings_map.items()
        }
        vectors_dict[SPARSE_VECTOR_NAME] = models.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist(),
        )
        return vectors_dict

    def _build_chunk_point(
        self,
        doc_id: str,
        chunk_data: Dict[str, Any],
        vectors_dict: Dict[str, Any],
        chunk_id: str,
        doc_payload_fields: Dict[str, Any],
    ) -> models.PointStruct:
        tag_section_type = (
            chunk_data.get("tag_section_type")
            or chunk_data.get("section_type")
            or chunk_data.get("sys_section_type")
        )
        return models.PointStruct(
            id=chunk_id,
            vector=vectors_dict,
            payload={
                "doc_id": doc_id,
                "tag_section_type": tag_section_type,
                **doc_payload_fields,
            },
        )

    def _upsert_batch_result(
        self,
        batch_res: Tuple[int, Dict[str, List[Any]], List[Any], int],
        chunks: List[Dict[str, Any]],
        doc_id: str,
        doc: Dict[str, Any],
        db: Database,
        backup_points: List[models.PointStruct],
    ) -> int:
        _, embeddings_map, sparse_res, start_idx = batch_res
        first_vec_list = next(iter(embeddings_map.values()))
        batch_len = len(first_vec_list)
        batch_chunks = chunks[start_idx : start_idx + batch_len]
        batch_points = []
        doc_payload_fields = self._build_doc_payload_fields(doc)

        for i, chunk_data in enumerate(batch_chunks):
            global_idx = start_idx + i
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{global_idx}"))
            sparse_vec = sparse_res[i]
            vectors_dict = self._build_vectors_dict(embeddings_map, sparse_vec, i)
            batch_points.append(
                self._build_chunk_point(
                    doc_id, chunk_data, vectors_dict, chunk_id, doc_payload_fields
                )
            )
            self._upsert_chunk_sidecar(chunk_id, doc_id, chunk_data)

        db.upsert_chunks(batch_points)
        backup_points.extend(batch_points)
        return len(batch_points)

    def _upsert_chunk_sidecar(
        self, chunk_id: str, doc_id: str, chunk_data: Dict[str, Any]
    ) -> None:
        tag_section_type = (
            chunk_data.get("tag_section_type")
            or chunk_data.get("section_type")
            or chunk_data.get("sys_section_type")
        )
        sys_fields = {
            "sys_chunk_elements": chunk_data.get("chunk_elements", []),
            "sys_tables": chunk_data.get("tables"),
            "sys_table_data": chunk_data.get("table_data"),
            "sys_bbox": [
                (
                    [
                        bbox[0],
                        (list(bbox[1]) if isinstance(bbox[1], tuple) else bbox[1]),
                    ]
                    if isinstance(bbox, tuple) and len(bbox) == 2
                    else bbox
                )
                for bbox in chunk_data.get("bbox", [])
            ],
            "sys_images": chunk_data.get("images"),
            "sys_elements": chunk_data.get("elements", []),
            "sys_item_types": chunk_data.get("item_types", []),
        }
        self.pg.upsert_chunk(
            chunk_id=str(chunk_id),
            doc_id=str(doc_id),
            sys_text=chunk_data.get("text"),
            sys_page_num=chunk_data.get("page_num"),
            sys_headings=chunk_data.get("headings"),
            sys_heading_path=None,
            tag_section_type=tag_section_type,
            sys_fields=sys_fields,
        )

    def _process_batches(
        self,
        batches: List[Tuple[int, List[str], List[str], int]],
        chunks: List[Dict[str, Any]],
        doc_id: str,
        doc: Dict[str, Any],
        db: Database,
        backup_points: List[models.PointStruct],
    ) -> int:
        total_batches = len(batches)
        chunks_indexed_count = 0

        if self.embedding_workers == 1:
            logger.info("  Processing batches sequentially (workers=1)")
            for batch_info in batches:
                res = self._embed_batch(batch_info, total_batches)
                chunks_indexed_count += self._upsert_batch_result(
                    res, chunks, doc_id, doc, db, backup_points
                )
        else:
            logger.info(
                "  Processing batches with %s parallel workers", self.embedding_workers
            )
            with ThreadPoolExecutor(max_workers=self.embedding_workers) as executor:
                futures = {
                    executor.submit(self._embed_batch, info, total_batches): info
                    for info in batches
                }
                for future in as_completed(futures):
                    res = future.result()
                    chunks_indexed_count += self._upsert_batch_result(
                        res, chunks, doc_id, doc, db, backup_points
                    )

        logger.info("  Total chunks upserted: %s", chunks_indexed_count)
        return chunks_indexed_count

    def _build_doc_text(self, doc: Dict[str, Any]) -> str:
        doc_text = doc.get("title", "")
        summary_fields = [
            "abstractive_summary",
            "full_summary",
            "key_content_sections",
            "centroid_summary",
        ]
        for field in summary_fields:
            if doc.get(field):
                doc_text += "\n\n" + str(doc.get(field))
                break
        return doc_text

    def _build_doc_embeddings(self, doc_text: str) -> Dict[str, Any]:
        doc_embeddings: Dict[str, Any] = {}
        if not doc_text or not str(doc_text).strip():
            logger.warning(
                "Skipping document embedding because document text is empty."
            )
            return doc_embeddings
        for name, model in self._dense_models.items():
            try:
                vec_config = DB_VECTORS.get(name)
                if not vec_config:
                    logger.warning(
                        "Vector config for %s not found despite model being loaded",
                        name,
                    )
                    continue
                is_azure = hasattr(model, "base_url")
                doc_input = (
                    doc_text
                    if is_azure
                    else add_passage_prefix(doc_text, vec_config["model_id"])
                )
                doc_embeddings[name] = list(model.embed([doc_input]))[0].tolist()
            except Exception as e:
                logger.warning("Failed to generate doc embedding for %s: %s", name, e)
        return doc_embeddings

    def _save_qdrant_backup(
        self,
        parsed_folder: str,
        backup_points: List[models.PointStruct],
        doc: Dict[str, Any],
        doc_updates: Dict[str, Any],
        doc_embeddings: Dict[str, Any],
        db: Database,
    ) -> None:
        try:
            zip_start_time = time.time()
            qdrant_dir = Path(parsed_folder) / "qdrant"
            if qdrant_dir.exists():
                shutil.rmtree(qdrant_dir)
            qdrant_dir.mkdir(parents=True)

            def json_serial(obj):
                if hasattr(obj, "model_dump"):
                    return obj.model_dump()
                if hasattr(obj, "dict"):
                    return obj.dict()
                if hasattr(obj, "tolist"):
                    return obj.tolist()
                return str(obj)

            points_file = qdrant_dir / f"{db.chunks_collection}.json"
            with open(points_file, "w", encoding="utf-8") as f:
                json.dump(backup_points, f, default=json_serial)

            doc_file = qdrant_dir / f"{db.documents_collection}.json"
            doc_snapshot = {
                "doc": doc,
                "doc_updates": doc_updates,
                "doc_embeddings": doc_embeddings,
            }
            with open(doc_file, "w", encoding="utf-8") as f:
                json.dump(doc_snapshot, f, default=json_serial)

            zip_path = Path(parsed_folder) / "qdrant.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in qdrant_dir.glob("*"):
                    zf.write(file_path, arcname=str(Path("qdrant") / file_path.name))

            zip_duration = time.time() - zip_start_time
            logger.info(
                "Saved Qdrant backup to %s (took %.2fs)", zip_path, zip_duration
            )
            shutil.rmtree(qdrant_dir)
        except Exception as e:
            logger.warning("Failed to save Qdrant backup: %s", e)

    def process_document(
        self, doc: Dict[str, Any], save_chunks: bool = False
    ) -> Dict[str, Any]:
        """
        Index a single document into Qdrant.

        Args:
            doc: Document dict with 'id', 'parsed_folder', 'title' fields

        Returns:
            Dict with success status and updates for database
        """
        self.ensure_setup()

        # Use instance database (respects data_source), not singleton
        db = self.db

        doc_id = doc.get("id")
        parsed_folder = doc.get("sys_parsed_folder")
        title = doc.get("map_title", "Unknown")

        if not doc_id:
            return self._build_failure(doc, "No document ID", "No document ID")

        if not parsed_folder:
            return self._build_failure(doc, "No parsed folder", "No parsed folder")

        # Normalize path - resolve relative paths using DATA_MOUNT_PATH
        parsed_folder = self._normalize_parsed_folder(parsed_folder)

        # Find JSON file in parsed folder
        json_path = self._resolve_json_path(parsed_folder)

        if not json_path.exists():
            return self._build_failure(
                doc, f"JSON not found: {json_path}", f"JSON not found: {json_path}"
            )

        logger.info("Indexing: %s", title)

        try:
            # 1. Chunk document
            chunks = self._chunk_document(str(json_path))

            # Initialize backup list for Qdrant points
            backup_points: List[models.PointStruct] = []

            # Persist Chunks to 'chunks' subfolder
            if save_chunks:
                self._save_chunks_file(parsed_folder, chunks)

            if not chunks:
                return self._build_failure(
                    doc, "No chunks generated", "No chunks generated"
                )

            # Remove existing chunks for this document to avoid duplicates
            try:
                # Delete from Postgres first
                pg_deleted = self.pg.delete_chunks_for_doc(str(doc_id))
                logger.info(
                    "  Deleted %s chunks from Postgres for doc %s", pg_deleted, doc_id
                )

                # Then delete from Qdrant
                db.client.delete(
                    collection_name=db.chunks_collection,
                    points_selector=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id",
                                match=models.MatchValue(value=str(doc_id)),
                            )
                        ]
                    ),
                    wait=True,
                )
                logger.info("  Cleared existing chunks from Qdrant for doc %s", doc_id)
            except Exception as exc:
                return self._build_failure(
                    doc,
                    f"Failed to delete existing chunks: {exc}",
                    "Failed to delete existing chunks",
                )

            # 2. Generate embeddings and upsert in batches (Streaming)
            # Filter out empty chunks to prevent Azure 400 errors
            chunks = self._filter_valid_chunks(chunks)
            texts = [chunk.get("text", "") for chunk in chunks]

            # Prepare texts for E5 if needed (not perfect if models mixed,
            # but handles the default/primary case)
            dense_texts = [add_passage_prefix(t, self.dense_model_id) for t in texts]

            if is_e5_model(self.dense_model_id):
                logger.info("  Using E5 prefix for default model indexing")

            logger.info("  Generating embeddings for %s chunks...", len(texts))

            batches = self._build_batches(texts, dense_texts)
            chunks_indexed_count = self._process_batches(
                batches, chunks, doc_id, doc, db, backup_points
            )

            doc_text = self._build_doc_text(doc)
            doc_embeddings = self._build_doc_embeddings(doc_text)

            # 4. Update document with embedding and status
            stage_updates = self.build_stage_updates(
                doc, success=True, chunks_count=chunks_indexed_count
            )
            doc_updates = {
                "sys_status": "indexed",
                "sys_chunk_count": chunks_indexed_count,
                "sys_error_message": None,
                **stage_updates,
            }
            doc_for_upsert = dict(doc)
            status_ts = doc_for_upsert.get("sys_status_timestamp")
            if isinstance(status_ts, datetime):
                doc_for_upsert["sys_status_timestamp"] = status_ts.isoformat()
            db.upsert_document(doc_id, doc_for_upsert, vector=doc_embeddings)
            self.pg.merge_doc_sys_fields(doc_id=str(doc_id), sys_fields=doc_updates)

            self._save_qdrant_backup(
                parsed_folder,
                backup_points,
                doc,
                doc_updates,
                doc_embeddings,
                db,
            )

            return {
                "success": True,
                "updates": doc_updates,
                "error": None,
                "chunks_indexed": chunks_indexed_count,
            }

        except Exception as e:
            logger.error("Exception indexing %s: %s", title, e)
            stage_updates = self.build_stage_updates(doc, success=False, error=str(e))
            return {
                "success": False,
                "updates": {
                    "sys_status": "index_failed",
                    "sys_error_message": str(e),
                    **stage_updates,
                },
                "error": str(e),
            }

    def teardown(self) -> None:
        """Release embedding models and chunker."""
        self._dense_models = {}
        self._primary_dense_model = None
        self._sparse_model = None
        self._tokenizer = None
        self._chunker_instance = None
        super().teardown()
