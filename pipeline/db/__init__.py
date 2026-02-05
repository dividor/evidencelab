"""Pipeline database package (compatibility re-exports)."""

import builtins

if "json" not in globals():
    import json as json  # noqa: F401

if "Path" not in globals():
    from pathlib import Path as Path  # noqa: F401

if "open" not in globals():
    open = builtins.open

if "QdrantClient" not in globals():
    from qdrant_client import QdrantClient as QdrantClient  # noqa: F401

import importlib  # noqa: E402

import pipeline.db.config as config  # noqa: E402

config = importlib.reload(config)
config.refresh_config()
_datasources_config = config._datasources_config

from pipeline.db.config import (  # noqa: E402
    CHUNKS_COLLECTION,
    DB_VECTORS,
    DEFAULT_DATA_SOURCE,
    DEFAULT_SEGMENT_NUMBER,
    DENSE_VECTOR_NAME,
    DENSE_VECTOR_SIZE,
    DOCUMENTS_COLLECTION,
    ENABLE_QUANTIZATION,
    HNSW_EF_CONSTRUCT,
    HNSW_M,
    HNSW_ON_DISK,
    MAX_SEGMENT_SIZE,
    QDRANT_HOST,
    QUANTIZATION_ALWAYS_RAM,
    QUANTIZATION_RESCORE,
    QUANTIZATION_TYPE,
    SPARSE_VECTOR_NAME,
    SUPPORTED_LLMS,
    SUPPORTED_RERANK_MODELS,
    UI_MODEL_COMBOS,
    VALID_METRICS,
    VECTOR_DISTANCE_METRIC,
    VECTORS_ON_DISK,
    _clean_model_name,
    clean_model_name,
    core_to_source_field,
    get_application_config,
    get_field_mapping,
    get_filter_fields,
    load_datasources_config,
    source_to_core_field,
)
from pipeline.db.database import Database, get_db, get_default_db  # noqa: E402
from pipeline.db.postgres_client import PostgresClient  # noqa: E402
from pipeline.db.stages import (  # noqa: E402
    StageInfo,
    Stages,
    make_stage,
    update_stages,
)

__all__ = [
    "CHUNKS_COLLECTION",
    "DB_VECTORS",
    "DEFAULT_DATA_SOURCE",
    "DEFAULT_SEGMENT_NUMBER",
    "DENSE_VECTOR_NAME",
    "DENSE_VECTOR_SIZE",
    "DOCUMENTS_COLLECTION",
    "ENABLE_QUANTIZATION",
    "HNSW_EF_CONSTRUCT",
    "HNSW_M",
    "HNSW_ON_DISK",
    "MAX_SEGMENT_SIZE",
    "QDRANT_HOST",
    "QUANTIZATION_ALWAYS_RAM",
    "QUANTIZATION_RESCORE",
    "QUANTIZATION_TYPE",
    "SPARSE_VECTOR_NAME",
    "SUPPORTED_RERANK_MODELS",
    "SUPPORTED_LLMS",
    "UI_MODEL_COMBOS",
    "VALID_METRICS",
    "VECTOR_DISTANCE_METRIC",
    "VECTORS_ON_DISK",
    "Database",
    "PostgresClient",
    "StageInfo",
    "Stages",
    "Path",
    "QdrantClient",
    "_clean_model_name",
    "_datasources_config",
    "clean_model_name",
    "core_to_source_field",
    "get_application_config",
    "get_db",
    "get_default_db",
    "get_field_mapping",
    "get_filter_fields",
    "load_datasources_config",
    "make_stage",
    "open",
    "json",
    "source_to_core_field",
    "update_stages",
]
