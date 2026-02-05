"""Qdrant database access for pipeline operations."""

from __future__ import annotations

import importlib
import logging
import os
import time
import warnings
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple, Union
from urllib.parse import urlparse

from qdrant_client.http import models
from qdrant_client.http.models import Distance, SparseVectorParams, VectorParams

from pipeline.db.config import (
    DEFAULT_DATA_SOURCE,
    DEFAULT_SEGMENT_NUMBER,
    ENABLE_QUANTIZATION,
    HNSW_EF_CONSTRUCT,
    HNSW_M,
    HNSW_ON_DISK,
    MAX_SEGMENT_SIZE,
    QUANTIZATION_ALWAYS_RAM,
    QUANTIZATION_TYPE,
    VECTOR_DISTANCE_METRIC,
    VECTORS_ON_DISK,
    clean_model_name,
    load_datasources_config,
)
from pipeline.db.postgres_client import PostgresClient

logger = logging.getLogger(__name__)


def _normalize_datetimes(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_datetimes(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_datetimes(val) for val in value]
    return value


def _swap_internal_host(host: str) -> str:
    if "://db" in host or "://qdrant" in host or host == "db" or host == "qdrant":
        logger.debug(
            "Detected internal Qdrant host '%s'. Swapping to 'localhost'.", host
        )
        host = host.replace("://db", "://localhost")
        host = host.replace("://qdrant", "://localhost")
        if host == "db":
            host = "localhost"
        if host == "qdrant":
            host = "localhost"
    return host


def _normalize_qdrant_url(host: str) -> str:
    if not (host.startswith("http://") or host.startswith("https://")):
        if ":" not in host:
            host = f"{host}:6333"
        host = f"http://{host}"
    return host


def _split_qdrant_url(host: str) -> tuple[str, str | None]:
    parsed = urlparse(host)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    prefix = parsed.path.strip("/") if parsed.path and parsed.path != "/" else None
    return base_url, prefix


class Database:
    def __init__(
        self, data_source: Optional[str] = None, *, create_indexes: bool = True
    ):
        """
        Initialize database connection with optional data source isolation.

        Args:
            data_source: Data source name for collection isolation. If provided,
                        collections will be named documents_{data_source} and
                        chunks_{data_source}. If None, uses DEFAULT_DATA_SOURCE env var.
        """
        # Set collection names based on data source
        source = data_source or DEFAULT_DATA_SOURCE
        self.data_source = source
        # Sanitize collection name: lowercase, replace spaces with underscores
        sanitized_source = source.lower().replace(" ", "_")
        self.documents_collection = f"documents_{sanitized_source}"
        self.chunks_collection = f"chunks_{sanitized_source}"
        self.pg = PostgresClient(source)
        self.pg.ensure_sidecar_tables()

        # Get Qdrant configuration
        host = os.getenv("QDRANT_HOST", "http://qdrant:6333")
        api_key = os.getenv("QDRANT_API_KEY")

        if not os.path.exists("/.dockerenv"):
            host = _swap_internal_host(host)
        host = _normalize_qdrant_url(host)
        base_url, prefix = _split_qdrant_url(host)

        logger.info(
            "Connecting to Qdrant at %s%s",
            base_url,
            f" with prefix '{prefix}'" if prefix else "",
        )

        # Use a single initialization path for both local and cloud
        qdrant_client = importlib.import_module("pipeline.db").QdrantClient
        # Suppress "Api key is used with an insecure connection" warning for internal
        # Docker network traffic (http://qdrant:6333). External access should use HTTPS.
        with warnings.catch_warnings():
            if base_url.startswith("http://") and api_key:
                warnings.filterwarnings(
                    "ignore",
                    message="Api key is used with an insecure connection",
                    category=UserWarning,
                )
            self.client = qdrant_client(
                url=base_url,
                api_key=api_key,
                prefix=prefix,
                timeout=int(
                    os.getenv(
                        "QDRANT_CLIENT_TIMEOUT",
                        60 if "cloud.qdrant.io" in base_url else 240,
                    )
                ),  # Default: 60s cloud, 240s local. Override for heavy ops.
            )

        logger.info(
            "Using collections: %s, %s",
            self.documents_collection,
            self.chunks_collection,
        )
        self.init_collections()
        if create_indexes:
            self.create_payload_indexes()  # Automatically create indexes for faceting

    def _load_pipeline_config(self) -> Dict[str, Any]:
        """Load pipeline configuration for the current data source from JSON."""
        # Using the global load_datasources_config logic but targeting specific datasource path
        config_data = load_datasources_config()
        # Handle new root structure if present
        datasources = config_data.get("datasources", config_data)

        datasource_key = next(
            (
                k
                for k, v in datasources.items()
                if v.get("data_subdir") == self.data_source or k == self.data_source
            ),
            None,
        )
        if datasource_key:
            return datasources[datasource_key].get("pipeline", {})
        return {}

    def _get_vector_config(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Parse vector configuration from JSON config.
        Returns (dense_vectors, sparse_vectors).
        """
        # Load full config to access global registry
        full_config = load_datasources_config()
        registry = full_config.get("supported_embedding_models", {})

        # Get pipeline config for this datasource
        pipeline_cfg = self._load_pipeline_config()
        index_config = pipeline_cfg.get("index", {})

        # Valid names are split into dense and sparse lists
        dense_names = index_config.get("dense_models", [])
        sparse_names = index_config.get("sparse_models", [])

        dense = {}
        sparse = {}

        # Process Dense Models
        for name in dense_names:
            if name not in registry:
                logger.warning(
                    "Dense model '%s' listed in config but not found in registry.",
                    name,
                )
                continue

            model_info = registry[name]
            if model_info.get("type", "dense") != "dense":
                logger.warning("Model '%s' is not marked as dense in registry.", name)
                continue

            dense[name] = {
                "size": model_info["size"],
                "model_id": model_info["model_id"],
                "source": model_info.get("source", "huggingface"),
            }

        # Process Sparse Models
        for name in sparse_names:
            if name not in registry:
                logger.warning(
                    "Sparse model '%s' listed in config but not found in registry.",
                    name,
                )
                continue

            model_info = registry[name]
            if model_info.get("type") != "sparse":
                logger.warning("Model '%s' is not marked as sparse in registry.", name)
                continue

            sparse[name] = {
                "model_id": model_info["model_id"],
                "source": model_info.get("source", "qdrant"),
            }

        return dense, sparse

    def _get_active_dense_model(self) -> Tuple[str, int]:
        """
        Identify the active dense model name and size.
        Returns (vector_name, vector_size).
        """
        config = self._load_pipeline_config()
        # Try to find the primary model active for chunking/queries
        # Use chunking config as the source of truth for "active" model
        primary_model_id = config.get("chunk", {}).get("dense_model")
        if not primary_model_id:
            raise ValueError("No dense_model found in chunk config")

        clean_name = clean_model_name(primary_model_id)

        # Verify it exists in our vectors list
        dense_vectors, _ = self._get_vector_config()

        if clean_name in dense_vectors:
            return clean_name, dense_vectors[clean_name]["size"]

        # Fallback logic if name mismatch or not found in list
        for name, v_cfg in dense_vectors.items():
            if v_cfg["model_id"] == primary_model_id:
                return name, v_cfg["size"]

        # If we are here, the configured chunk model is not in the enabled models list.
        # This is invalid config, but we might default to first enabled dense vector?
        raise ValueError(
            f"Active model {primary_model_id} not found/enabled in models list."
        )

        raise ValueError("No enabled dense vectors found in configuration")

    def init_collections(self):
        """Initialize collections if they don't exist."""
        # Get existing collections
        existing_collections = {
            c.name for c in self.client.get_collections().collections
        }

        self._ensure_documents_collection(existing_collections)
        self._ensure_chunks_collection(existing_collections)

    def _ensure_documents_collection(self, existing_collections: set[str]) -> None:
        if self.documents_collection in existing_collections:
            self._validate_collection_vectors(self.documents_collection)
            return
        logger.info("Creating collection: %s", self.documents_collection)
        distance_metric = getattr(Distance, VECTOR_DISTANCE_METRIC)
        dense_vectors, _ = self._get_vector_config()
        vectors_config = self._build_dense_vectors_config(
            dense_vectors, distance_metric
        )
        collection_config = {
            "collection_name": self.documents_collection,
            "vectors_config": vectors_config,
        }
        self._apply_quantization(collection_config)
        self._apply_optimizers(collection_config)
        self.client.create_collection(**collection_config)

    def _ensure_chunks_collection(self, existing_collections: set[str]) -> None:
        if self.chunks_collection in existing_collections:
            self._validate_collection_vectors(self.chunks_collection)
            return
        logger.info("Creating collection: %s", self.chunks_collection)
        distance_metric = getattr(Distance, VECTOR_DISTANCE_METRIC)
        dense_vectors, sparse_vectors = self._get_vector_config()
        vectors_config = self._build_dense_vectors_config(
            dense_vectors, distance_metric
        )
        sparse_vectors_config = self._build_sparse_vectors_config(sparse_vectors)
        collection_config = {
            "collection_name": self.chunks_collection,
            "vectors_config": vectors_config,
            "sparse_vectors_config": sparse_vectors_config,
        }
        self._apply_quantization(collection_config)
        self._apply_optimizers(collection_config)
        self.client.create_collection(**collection_config)

    def _build_dense_vectors_config(self, dense_vectors: dict, distance_metric) -> dict:
        vectors_config = {}
        for vec_name, vec_config in dense_vectors.items():
            vectors_config[vec_name] = VectorParams(
                size=vec_config["size"],
                distance=distance_metric,
                on_disk=VECTORS_ON_DISK,
                hnsw_config=models.HnswConfigDiff(
                    m=HNSW_M,
                    ef_construct=HNSW_EF_CONSTRUCT,
                    on_disk=HNSW_ON_DISK,
                ),
            )
        return vectors_config

    def _build_sparse_vectors_config(self, sparse_vectors: dict) -> dict:
        return {vec_name: SparseVectorParams() for vec_name in sparse_vectors}

    def _apply_quantization(self, collection_config: dict) -> None:
        if not ENABLE_QUANTIZATION:
            return
        if QUANTIZATION_TYPE == "int8":
            collection_config["quantization_config"] = models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8,
                    always_ram=QUANTIZATION_ALWAYS_RAM,
                ),
            )
        elif QUANTIZATION_TYPE == "binary":
            collection_config["quantization_config"] = models.BinaryQuantization(
                binary=models.BinaryQuantizationConfig(
                    always_ram=QUANTIZATION_ALWAYS_RAM,
                ),
            )

    def _apply_optimizers(self, collection_config: dict) -> None:
        if DEFAULT_SEGMENT_NUMBER > 0:
            collection_config["optimizers_config"] = models.OptimizersConfigDiff(
                default_segment_number=DEFAULT_SEGMENT_NUMBER,
                max_segment_size=MAX_SEGMENT_SIZE,
            )

    def _validate_collection_vectors(self, collection_name: str) -> None:
        """
        Validate that an existing collection's vector config matches .env settings.
        Raises ValueError if there's a mismatch to prevent silent failures.
        """
        try:
            collection_info = self.client.get_collection(collection_name)
            vectors_config = collection_info.config.params.vectors

            # Check if expected vector name exists
            active_name, active_size = self._get_active_dense_model()

            if active_name not in vectors_config:
                existing_vectors = list(vectors_config.keys())
                raise ValueError(
                    f"Collection '{collection_name}' has wrong vector config!\n"
                    f"  Expected vector: {active_name} (from config)\n"
                    f"  Existing vectors: {existing_vectors}\n"
                    f"  To fix: Delete collection and let it recreate with correct config:\n"
                    f"    curl -X DELETE 'http://localhost:6333/collections/{collection_name}'"
                )

            # Validate vector size matches
            existing_size = vectors_config[active_name].size
            if existing_size != active_size:
                logger.error(
                    "Validation Mismatch: DENSE_VECTOR_NAME=%s, existing_size=%s, "
                    "DENSE_VECTOR_SIZE=%s",
                    active_name,
                    existing_size,
                    active_size,
                )
                raise ValueError(
                    f"Collection '{collection_name}' has wrong vector size!\n"
                    f"  Expected: {active_size} (from config)\n"
                    f"  Existing: {existing_size}\n"
                    f"  To fix: Delete collection and let it recreate with correct config"
                )

            logger.debug(
                "Collection %s validated: %s (%sd)",
                collection_name,
                active_name,
                active_size,
            )
        except ValueError:
            raise  # Re-raise validation errors
        except Exception as exc:
            logger.warning("Could not validate collection %s: %s", collection_name, exc)

    def clear_all_data(self):
        """
        Clear all data from both collections for this data source.
        Recreates the collections to ensure a complete reset.
        """
        logger.info(
            "Clearing all data from collections: %s, %s",
            self.documents_collection,
            self.chunks_collection,
        )

        try:
            # Delete documents collection
            self.client.delete_collection(collection_name=self.documents_collection)
            logger.info("Deleted %s", self.documents_collection)
        except Exception as exc:
            logger.warning("Could not delete %s: %s", self.documents_collection, exc)

        try:
            # Delete chunks collection
            self.client.delete_collection(collection_name=self.chunks_collection)
            logger.info("Deleted %s", self.chunks_collection)
        except Exception as exc:
            logger.warning("Could not delete %s: %s", self.chunks_collection, exc)

        # Recreate both collections
        self.init_collections()

        # Recreate indexes
        self.create_payload_indexes()

        logger.info("Data cleared and collections recreated successfully")

    def create_payload_indexes(self):
        """Create payload indexes for faceting on both collections.
        Creates indexes immediately when collections are initialized to support filtering.
        """
        logger.info("Creating payload indexes for faceting...")

        # Fields to index for faceting and filtering
        facet_fields = [
            ("is_duplicate", models.PayloadSchemaType.BOOL),
            ("map_organization", models.PayloadSchemaType.KEYWORD),
            ("map_document_type", models.PayloadSchemaType.KEYWORD),
            ("map_published_year", models.PayloadSchemaType.KEYWORD),
            ("map_country", models.PayloadSchemaType.KEYWORD),
            ("map_region", models.PayloadSchemaType.KEYWORD),
            ("map_theme", models.PayloadSchemaType.KEYWORD),
            ("map_language", models.PayloadSchemaType.KEYWORD),
            ("sys_language", models.PayloadSchemaType.KEYWORD),
            ("map_title", models.PayloadSchemaType.TEXT),
        ]

        # Additional fields for chunks collection (used in search filtering)
        chunks_only_fields = [
            ("doc_id", models.PayloadSchemaType.KEYWORD),
            ("tag_section_type", models.PayloadSchemaType.KEYWORD),
            ("sys_language", models.PayloadSchemaType.KEYWORD),
        ]

        # Add configured taxonomies to indexing (e.g. tag_sdg)
        pipeline_cfg = self._load_pipeline_config()
        taxonomies = pipeline_cfg.get("tag", {}).get("taxonomies", {})
        for tax_key in taxonomies:
            field_name = f"tag_{tax_key}"
            facet_fields.append((field_name, models.PayloadSchemaType.KEYWORD))
            # Also add to chunks? Yes, usually.
            # facet_fields is used for both.

        # Create indexes on documents collection
        for field_name, field_type in facet_fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.documents_collection,
                    field_name=field_name,
                    field_schema=field_type,
                )
                logger.debug(
                    "Created index on %s.%s", self.documents_collection, field_name
                )
            except Exception:
                # Silently skip errors (index may already exist)
                pass

        # Create indexes on chunks collection (for denormalized metadata)
        for field_name, field_type in facet_fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.chunks_collection,
                    field_name=field_name,
                    field_schema=field_type,
                )
                logger.debug(
                    "Created index on %s.%s", self.chunks_collection, field_name
                )
            except Exception:
                # Silently skip errors (index may already exist)
                pass

        # Create chunks-only indexes
        for field_name, field_type in chunks_only_fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.chunks_collection,
                    field_name=field_name,
                    field_schema=field_type,
                )
                logger.debug(
                    "Created index on %s.%s", self.chunks_collection, field_name
                )
            except Exception:
                # Silently skip errors (index may already exist)
                pass

        logger.info("Payload indexes ready")

    def upsert_document(
        self,
        doc_id: str,
        metadata: Dict[str, Any],
        vector: Optional[Union[List[float], Dict[str, List[float]]]] = None,
        max_retries: int = 3,
    ):
        """Upsert a document metadata record with optional embedding vector(s)."""
        metadata = _normalize_datetimes(dict(metadata))
        # Convert string ID to integer if needed (Qdrant uses integer IDs)
        if isinstance(doc_id, str):
            try:
                doc_id = int(doc_id)  # type: ignore[assignment]
            except ValueError:
                # If it's not a valid integer string, it might be a UUID - leave as is
                pass

        # Prepare vector dict
        vectors = {}
        if vector:
            if isinstance(vector, dict):
                # Already a dictionary of named vectors
                vectors = vector
            else:
                # Single legacy vector list, use primary name
                name, _ = self._get_active_dense_model()
                vectors[name] = vector

        qdrant_payload, sys_fields = self._split_doc_payload(metadata)
        if sys_fields:
            self.pg.merge_doc_sys_fields(doc_id=str(doc_id), sys_fields=sys_fields)

        point = models.PointStruct(
            id=doc_id,
            vector=vectors if vectors else {},
            payload=qdrant_payload,
        )

        last_error = None
        for attempt in range(max_retries):
            try:
                self.client.upsert(
                    collection_name=self.documents_collection,
                    points=[point],
                    wait=False,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        "Qdrant upsert failed (attempt %s/%s), retrying in %ss: %s",
                        attempt + 1,
                        max_retries,
                        wait_time,
                        exc,
                    )
                    time.sleep(wait_time)

        raise last_error

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve document metadata by ID."""
        # Convert string ID to integer if needed (Qdrant uses integer IDs)
        if isinstance(doc_id, str):
            try:
                doc_id = int(doc_id)  # type: ignore[assignment]
            except ValueError:
                # If it's not a valid integer string, it might be a UUID - leave as is
                pass

        results = self.client.retrieve(
            collection_name=self.documents_collection, ids=[doc_id]
        )
        if not results:
            return None
        qdrant_payload = results[0].payload or {}
        pg_payload = self.pg.fetch_docs([doc_id]).get(str(doc_id), {})
        merged = dict(qdrant_payload)
        merged.update(pg_payload)
        sys_data = merged.get("sys_data")
        if isinstance(sys_data, dict):
            if not merged.get("sys_parsed_folder"):
                merged["sys_parsed_folder"] = sys_data.get("sys_parsed_folder")
            if not merged.get("sys_filepath"):
                merged["sys_filepath"] = sys_data.get("sys_filepath")
        return merged or None

    def document_exists(self, url: str) -> bool:
        """Check if a document with the given URL exists."""
        # Filter by URL in payload
        results = self.client.scroll(
            collection_name=self.documents_collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(key="url", match=models.MatchValue(value=url))
                ]
            ),
            limit=1,
        )
        return len(results[0]) > 0

    def get_documents_by_status(
        self, status: str, exclude_duplicates: bool = True, year: int = None
    ) -> List[Dict[str, Any]]:
        """Retrieve documents with a specific status, including their IDs.

        Args:
            status: The status to filter by
            exclude_duplicates: If True, exclude documents marked as is_duplicate
            year: Optional year to filter by
        """
        docs = self.pg.fetch_docs_by_status(status=status, year=year)
        if exclude_duplicates:
            docs = [doc for doc in docs if not doc.get("is_duplicate")]
        return docs

    def get_years_for_status(self, status: str) -> List[int]:
        """Get list of available years for documents with a specific status.

        Args:
            status: Document status to filter by

        Returns:
            List of years (integers) sorted descending
        """
        year_values = self.pg.fetch_years_for_status(status)
        years = []
        for year_str in year_values:
            try:
                if year_str and str(year_str).isdigit():
                    years.append(int(year_str))
            except (ValueError, TypeError):
                continue

        return sorted(years, reverse=True)

    def get_paginated_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, str]] = None,
        sort_by: str = "year",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """
        Get documents with server-side pagination, filtering, and sorting.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            filters: Dictionary of field -> value to filter by
            sort_by: Field to sort by (e.g., "year", "title")
            sort_order: "asc" or "desc"

        Returns:
            Dict containing "documents", "total", and pagination info
        """
        docs = self.pg.fetch_all_docs()
        filtered_docs = self._filter_documents_in_memory(docs, filters)
        sorted_docs = self._sort_documents_in_memory(
            filtered_docs, sort_by=sort_by, sort_order=sort_order
        )
        total_count = len(sorted_docs)
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1
        start_idx, end_idx = self._page_slice(page, page_size, total_count)
        docs = sorted_docs[start_idx:end_idx]
        return {
            "documents": docs,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def _map_document_field(self, key: str) -> str:
        if key.startswith("map_") or key.startswith("sys_"):
            return key
        field_map = {
            "organization": "map_organization",
            "document_type": "map_document_type",
            "published_year": "map_published_year",
            "title": "map_title",
            "language": "map_language",
            "country": "map_country",
            "region": "map_region",
            "theme": "map_theme",
            "status": "sys_status",
            "file_format": "sys_file_format",
            "file_size_mb": "sys_file_size_mb",
            "filepath": "sys_filepath",
            "parsed_folder": "sys_parsed_folder",
            "metadata_checksum": "sys_metadata_checksum",
            "file_checksum": "sys_file_checksum",
            "stages": "sys_stages",
            "full_summary": "sys_full_summary",
            "toc": "sys_toc",
            "toc_classified": "sys_toc_classified",
            "toc_approved": "sys_toc_approved",
            "error_message": "sys_error_message",
            "taxonomies": "sys_taxonomies",
        }
        return field_map.get(key, key)

    def _build_documents_filter(
        self, filters: Optional[Dict[str, str]]
    ) -> models.Filter:
        must_conditions: List[models.Condition] = []
        must_not_conditions = [
            models.FieldCondition(
                key="is_duplicate",
                match=models.MatchValue(value=True),
            )
        ]
        if not filters:
            return models.Filter(must=must_conditions, must_not=must_not_conditions)
        for key, value in filters.items():
            if not value or not value.strip():
                continue
            if key == "search":
                must_conditions.append(
                    models.Filter(should=self._search_conditions(value))
                )
            elif key in ["title", "full_summary"]:
                field_key = self._map_document_field(key)
                must_conditions.append(
                    models.FieldCondition(
                        key=field_key,
                        match=models.MatchText(text=value),
                    )
                )
            else:
                field_key = self._map_document_field(key)
                must_conditions.append(
                    models.FieldCondition(
                        key=field_key,
                        match=models.MatchValue(value=value),
                    )
                )
        return models.Filter(must=must_conditions, must_not=must_not_conditions)

    @staticmethod
    def _text_matches(value: str, needle: str) -> bool:
        return needle.lower() in value.lower()

    def _doc_matches_filter(self, doc: Dict[str, Any], key: str, value: str) -> bool:
        if key == "search":
            haystack = " ".join(
                [
                    str(doc.get("map_title", "") or ""),
                    str(doc.get("sys_full_summary", "") or ""),
                ]
            )
            return self._text_matches(haystack, value)

        field_key = self._map_document_field(key)

        # Special handling for taxonomies stored in sys_taxonomies
        if doc.get("sys_taxonomies") and isinstance(doc["sys_taxonomies"], dict):
            # Check if key is a taxonomy name (e.g. "sdg")
            # If the filter key matches a key in sys_taxonomies, check intersection
            if key in doc["sys_taxonomies"]:
                tax_values = doc["sys_taxonomies"][key]
                if isinstance(tax_values, list):
                    return value in tax_values
                return str(tax_values) == str(value)

        doc_value = doc.get(field_key)
        if doc_value is None:
            return False
        if key in ["title", "full_summary"]:
            return self._text_matches(str(doc_value), value)
        if isinstance(doc_value, str) and "," in doc_value:
            values = [item.strip() for item in doc_value.split(",") if item.strip()]
            return value in values
        return str(doc_value) == str(value)

    def _filter_documents_in_memory(
        self, docs: List[Dict[str, Any]], filters: Optional[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        if not filters:
            return docs

        filtered: List[Dict[str, Any]] = []
        for doc in docs:
            include = True
            for key, value in filters.items():
                if not value or not value.strip():
                    continue
                if not self._doc_matches_filter(doc, key, value):
                    include = False
                    break
            if include:
                filtered.append(doc)
        return filtered

    def _sort_documents_in_memory(
        self, docs: List[Dict[str, Any]], sort_by: str, sort_order: str
    ) -> List[Dict[str, Any]]:
        reverse = sort_order.lower() == "desc"

        def _get_last_updated(d: Dict[str, Any]) -> str:
            stages = d.get("sys_stages")
            if not stages and isinstance(d.get("sys_data"), dict):
                stages = d["sys_data"].get("sys_stages")

            stages = stages or {}
            timestamps = []
            for stage_info in stages.values():
                if isinstance(stage_info, dict) and stage_info.get("at"):
                    timestamps.append(stage_info["at"])
            return max(timestamps) if timestamps else ""

        def sort_key_fn(d):
            if sort_by == "year":
                return d.get("map_published_year")
            elif sort_by == "last_updated":
                return _get_last_updated(d)
            elif sort_by == "title":
                return (d.get("map_title") or d.get("title") or "").lower()
            return d.get(sort_by)

        def _safe_value(value: Any) -> Any:
            if value is None:
                return ""
            return value

        return sorted(docs, key=lambda d: _safe_value(sort_key_fn(d)), reverse=reverse)

    def _search_conditions(self, value: str) -> list[models.FieldCondition]:
        return [
            models.FieldCondition(key=field, match=models.MatchText(text=value))
            for field in ["map_title", "sys_full_summary"]
        ]

    def _count_documents(
        self, query_filter: models.Filter, page_size: int
    ) -> tuple[int, int]:
        count_result = self.client.count(
            collection_name=self.documents_collection,
            count_filter=query_filter,
        )
        total_count = count_result.count
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1
        return total_count, total_pages

    def _page_slice(
        self, page: int, page_size: int, total_count: int
    ) -> tuple[int, int]:
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_count)
        return start_idx, end_idx

    def _scroll_documents(self, query_filter: models.Filter, end_idx: int) -> List[Any]:
        all_points: List[Any] = []
        next_offset = None
        while len(all_points) < end_idx:
            chunk_limit = min(1000, end_idx - len(all_points))
            results, next_offset = self.client.scroll(
                collection_name=self.documents_collection,
                scroll_filter=query_filter,
                limit=chunk_limit,
                offset=next_offset,
                with_payload=True,
            )
            if not results:
                break
            all_points.extend(results)
            if next_offset is None:
                break
        return all_points

    def _format_documents(
        self, points: List[Any], start_idx: int, end_idx: int
    ) -> List[Dict[str, Any]]:
        paginated_points = points[start_idx:end_idx]
        return [
            {"id": str(point.id), **point.payload}
            for point in paginated_points
            if point.payload
        ]

    def find_documents_by_file_checksum(
        self, checksum: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find documents with the specified file checksum."""
        return self.pg.fetch_docs_by_file_checksum(checksum, limit=limit)

    def update_document(
        self,
        doc_id: str,
        updates: Dict[str, Any],
        max_retries: int = 3,
        wait: bool = False,
    ):
        """Update specific fields of a document."""
        if "sys_status" in updates and "sys_last_updated" not in updates:
            updates["sys_last_updated"] = time.time()
        qdrant_updates, sys_fields = self._split_doc_payload(updates)
        if sys_fields:
            self.pg.merge_doc_sys_fields(doc_id=str(doc_id), sys_fields=sys_fields)
        if not qdrant_updates:
            return
        # Convert string ID to integer if needed (Qdrant uses integer IDs)
        if isinstance(doc_id, str):
            try:
                doc_id = int(doc_id)  # type: ignore[assignment]
            except ValueError:
                # If it's not a valid integer string, it might be a UUID - leave as is
                pass

        last_error = None
        for attempt in range(max_retries):
            try:
                self.client.set_payload(
                    collection_name=self.documents_collection,
                    payload=qdrant_updates,
                    points=[doc_id],
                    wait=wait,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning(
                        "Qdrant update failed (attempt %s/%s), retrying in %ss: %s",
                        attempt + 1,
                        max_retries,
                        wait_time,
                        exc,
                    )
                    time.sleep(wait_time)

        raise last_error

    def delete_document_chunks(self, doc_id: str) -> int:
        """
        Delete all chunks for a specific document.

        Returns:
            Number of deleted chunks
        """
        filter_conditions = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id", match=models.MatchValue(value=str(doc_id))
                )
            ]
        )

        # Count chunks before delete
        chunk_count = self.client.count(
            collection_name=self.chunks_collection,
            count_filter=filter_conditions,
        ).count

        # Delete
        self.client.delete(
            collection_name=self.chunks_collection,
            points_selector=filter_conditions,
            wait=True,
        )

        logger.info("Deleted %s chunks for document %s", chunk_count, doc_id)
        return chunk_count

    def collection_exists(self, collection_name: str) -> bool:
        """Check if a Qdrant collection exists."""
        try:
            collections = self.client.get_collections().collections
            return any(c.name == collection_name for c in collections)
        except Exception:
            return False

    def get_all_documents(self) -> Generator[Dict[str, Any], None, None]:
        """Iterate through all documents in the collection."""
        for doc in self.pg.fetch_all_docs():
            payload = dict(doc)
            payload.pop("id", None)
            yield payload

    def get_all_documents_projection(
        self, fields: List[str]
    ) -> Generator[Dict[str, Any], None, None]:
        """Iterate through all documents with only specific fields."""
        for doc in self.pg.fetch_all_docs():
            payload = dict(doc)
            payload.pop("id", None)
            yield {key: payload.get(key) for key in fields if key in payload}

    def get_all_documents_with_ids(
        self,
    ) -> Generator[tuple[str, Dict[str, Any]], None, None]:
        """Iterate through all documents with IDs included."""
        for doc in self.pg.fetch_all_docs():
            doc_id = str(doc.get("id"))
            payload = dict(doc)
            payload.pop("id", None)
            yield doc_id, payload

    def _split_doc_payload(
        self, metadata: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        qdrant_payload: Dict[str, Any] = {}
        sys_fields: Dict[str, Any] = {}
        for key, value in metadata.items():
            if key == "pipeline_elapsed_seconds":
                sys_fields["sys_pipeline_elapsed_seconds"] = value
                continue
            if key.startswith("sys_"):
                if isinstance(value, datetime):
                    value = value.isoformat()
                sys_fields[key] = value
                continue
            if key.startswith(("src_", "map_")) or key == "is_duplicate":
                qdrant_payload[key] = value
        return qdrant_payload, sys_fields

    def upsert_chunks(self, points: List[models.PointStruct]):
        """Upsert chunk vectors into the collection."""
        if not points:
            return

        count = len(points)
        logger.info("    [Qdrant] Calling upsert_chunks (%s points)...", count)

        start_time = time.time()
        self.client.upsert(
            collection_name=self.chunks_collection, points=points, wait=True
        )
        elapsed = time.time() - start_time
        logger.info("    [Qdrant] upsert_chunks finished in %.2fs", elapsed)

    def facet(
        self,
        collection_name: str,
        key: str,
        filter_conditions: Optional[models.Filter] = None,
        limit: int = 10,
        exact: bool = False,
    ) -> Dict[str, int]:
        """
        Get facet values and counts for a field.

        Args:
            collection_name: Collection to facet on
            key: Field name to facet on
            filter_conditions: Optional filters to apply
            limit: Maximum number of facet values to return
            exact: Whether to use exact counting (slower but accurate)

        Returns:
            Dictionary mapping field values to their counts
        """
        result = self.client.facet(
            collection_name=collection_name,
            key=key,
            facet_filter=filter_conditions,
            limit=limit,
            exact=exact,
        )
        if isinstance(result, dict):
            hits = result.get("hits", [])
        else:
            hits = result.hits
        return {hit.value: hit.count for hit in hits}

    def facet_documents(
        self,
        key: str,
        filter_conditions: Optional[models.Filter] = None,
        limit: int = 10,
        exact: bool = False,
    ) -> Dict[str, int]:
        """
        Get facet values and counts for a field in documents collection.

        Args:
            key: Field name to facet on
            filter_conditions: Optional filters to apply
            limit: Maximum number of facet values to return
            exact: Whether to use exact counting (slower but accurate)

        Returns:
            Dictionary mapping field values to their counts
        """
        result = self.facet(
            collection_name=self.documents_collection,
            key=key,
            filter_conditions=filter_conditions,
            limit=limit,
            exact=exact,
        )
        # facet() already normalizes to a value->count dict
        return result

    def count_documents(self) -> int:
        """Return count of documents in this data source's collection."""
        return self.client.count(collection_name=self.documents_collection).count

    def count_documents_with_filter(
        self, filter_conditions: models.Filter, exact: bool = True
    ) -> int:
        """Return count of documents matching the filter."""
        return self.client.count(
            collection_name=self.documents_collection,
            count_filter=filter_conditions,
            exact=exact,
        ).count

    def count_chunks(self, filters: Optional[models.Filter] = None) -> int:
        """Return count of chunks in this data source's collection."""
        return self.client.count(
            collection_name=self.chunks_collection, count_filter=filters
        ).count


_db_cache: Dict[Optional[str], Database] = {}


def get_db(data_source: Optional[str] = None) -> Database:
    """
    Factory function to get a Database instance for a specific data source.

    Args:
        data_source: Data source name (e.g., 'uneg', 'gcf'). If None, uses DEFAULT_DATA_SOURCE.

    Returns:
        Database instance configured for the specified data source.

    Example:
        # Get db for UNEG data
        uneg_db = get_db("uneg")

        # Get db for GCF data
        gcf_db = get_db("gcf")
    """
    if data_source not in _db_cache:
        _db_cache[data_source] = Database(data_source=data_source)
    return _db_cache[data_source]


# Singleton instance (uses DEFAULT_DATA_SOURCE)
# Lazy initialization to avoid connection issues at import time
_db_instance = None


def get_default_db() -> Database:
    """Get the default Database singleton instance (lazy initialization)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
