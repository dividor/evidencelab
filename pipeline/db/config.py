"""Datasource configuration and vector settings for pipeline DB access."""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Dict

from dotenv import load_dotenv
from qdrant_client.http.models import Distance

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Qdrant Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "http://qdrant:6333")

# Default data source for collection naming (collections become documents_{source}, chunks_{source})
DEFAULT_DATA_SOURCE = os.getenv("DEFAULT_DATA_SOURCE", "uneg")

# Legacy collection name support (for backwards compatibility)
DOCUMENTS_COLLECTION = os.getenv(
    "DOCUMENTS_COLLECTION", f"documents_{DEFAULT_DATA_SOURCE}"
)
CHUNKS_COLLECTION = os.getenv("CHUNKS_COLLECTION", f"chunks_{DEFAULT_DATA_SOURCE}")

DEFAULT_SEGMENT_NUMBER = int(os.getenv("DEFAULT_SEGMENT_NUMBER", "0"))
MAX_SEGMENT_SIZE = int(os.getenv("MAX_SEGMENT_SIZE", "200000"))

_datasources_config: Dict[str, Any] = {}


def load_datasources_config() -> Dict[str, Any]:
    """Load datasources configuration from JSON."""
    global _datasources_config
    db_module = importlib.import_module("pipeline.db")
    Path_cls = db_module.Path
    open_func = db_module.open
    json_module = db_module.json

    path_to_check = Path_cls(__file__).resolve().parents[2] / "config.json"
    config_path = path_to_check
    if not config_path.exists():
        # Fallback to old name if new doesn't exist? Or just fail?
        # Let's try legacy name if new one missing for smooth dev transition
        legacy_path = Path_cls("datasources.config.json")
        if legacy_path.exists():
            config_path = legacy_path
        else:
            logger.warning("Config file %s not found. Using defaults.", config_path)
            _datasources_config = {}
            return _datasources_config

    with open_func(config_path, encoding="utf-8") as handle:
        _datasources_config = json_module.load(handle)
    return _datasources_config


DB_VECTORS: Dict[str, Dict[str, Any]] = {}
SUPPORTED_LLMS: Dict[str, Dict[str, Any]] = {}
SUPPORTED_RERANK_MODELS: Dict[str, Dict[str, Any]] = {}
UI_MODEL_COMBOS: Dict[str, Dict[str, Any]] = {}
_config: Dict[str, Any] = {}
_app_config: Dict[str, Any] = {}
_search_config: Dict[str, Any] = {}

# Legacy constants for backward compatibility
# DB_VECTORS = "vectors"  # Removed to prevent collision with config dict
# Default Vector Name (Must match a key in supported_embedding_models)
DENSE_VECTOR_NAME = "e5_large"

# Default to "Cosine" if not defined elsewhere
VECTOR_DISTANCE_METRIC = "COSINE"
DENSE_VECTOR_SIZE = 1024
SPARSE_VECTOR_NAME = "bm25"  # Just in case


def refresh_config() -> None:
    """Reload config-driven settings for vectors and LLMs."""
    global _config, _app_config, _search_config, _datasources_config
    global DB_VECTORS
    global SUPPORTED_LLMS
    global SUPPORTED_RERANK_MODELS
    global UI_MODEL_COMBOS
    global DENSE_VECTOR_NAME
    global DENSE_VECTOR_SIZE

    _datasources_config = {}
    _config = load_datasources_config()

    DB_VECTORS = {}
    if "supported_embedding_models" in _config:
        for model_name, model_info in _config["supported_embedding_models"].items():
            if model_info.get("type") == "dense":
                DB_VECTORS[model_name] = {
                    "size": model_info["size"],
                    "enabled": True,  # Default to enabled
                    "model_id": model_info["model_id"],
                    "source": model_info.get("source", "huggingface"),
                }

    SUPPORTED_LLMS = {}
    if "supported_llms" in _config:
        for model_name, model_info in _config["supported_llms"].items():
            llm_config: Dict[str, Any] = {
                "model": model_info.get("model"),
                "provider": model_info.get("provider", "huggingface"),
            }
            # Add inference_provider if present
            if "inference_provider" in model_info:
                llm_config["inference_provider"] = model_info.get("inference_provider")
            SUPPORTED_LLMS[model_name] = llm_config

    SUPPORTED_RERANK_MODELS = {}
    if "supported_rerank_models" in _config:
        for model_name, model_info in _config["supported_rerank_models"].items():
            SUPPORTED_RERANK_MODELS[model_name] = {
                "api_version": model_info.get("api_version"),
                "endpoint": model_info.get("endpoint"),
                "endpoint_url": model_info.get("endpoint_url"),
                "model_id": model_info.get("model_id", model_name),
                "source": model_info.get("source", "huggingface"),
                "provider": model_info.get("provider"),
            }

    UI_MODEL_COMBOS = {}
    if "ui_model_combos" in _config:
        UI_MODEL_COMBOS = _config.get("ui_model_combos", {})

    _app_config = _config.get("application", {})
    _search_config = _app_config.get("search", {})
    DENSE_VECTOR_NAME = _search_config.get("default_dense_model", "e5_large")
    DENSE_VECTOR_SIZE = 1024
    if DENSE_VECTOR_NAME in DB_VECTORS:
        DENSE_VECTOR_SIZE = DB_VECTORS[DENSE_VECTOR_NAME]["size"]

    if "ui_model_combos" in _config:
        from utils.config_validator import validate_ui_model_combos  # noqa: PLC0415

        combo_errors = validate_ui_model_combos(_config)
        if combo_errors:
            raise ValueError(
                "Invalid ui_model_combos configuration: " + "; ".join(combo_errors)
            )


refresh_config()


def get_field_mapping(data_source: str) -> Dict[str, str]:
    """Get field mapping for a data source (core field -> source field)."""
    config = load_datasources_config()
    # Handle new config structure (datasources key) or legacy structure
    datasources = config.get("datasources", config)

    # If datasources is not a dict (e.g. if config has other top level keys but no datasources),
    # we might be iterating over the wrong thing, so be careful.
    if not isinstance(datasources, dict):
        return {}

    for domain_config in datasources.values():
        if (
            isinstance(domain_config, dict)
            and domain_config.get("data_subdir") == data_source
        ):
            return domain_config.get("field_mapping", {})
    return {}


def get_filter_fields(data_source: str) -> Dict[str, str]:
    """Get filter fields for a data source (core field -> display label)."""
    config = load_datasources_config()
    # Handle new config structure (datasources key) or legacy structure
    datasources = config.get("datasources", config)

    if not isinstance(datasources, dict):
        return {}

    for domain_config in datasources.values():
        if (
            isinstance(domain_config, dict)
            and domain_config.get("data_subdir") == data_source
        ):
            return domain_config.get("filter_fields", {})
    return {}


def core_to_source_field(data_source: str, core_field: str) -> str:
    """Map a core field name to source field name."""
    mapping = get_field_mapping(data_source)
    mapping_value = mapping.get(core_field, core_field)
    # If the mapping is a fixed_value, there's no source field, so return the core field name
    if isinstance(mapping_value, str) and mapping_value.startswith("fixed_value:"):
        return core_field
    return mapping_value


def source_to_core_field(data_source: str, source_field: str) -> str:
    """Map source field name to core field name."""
    mapping = get_field_mapping(data_source)
    reverse_mapping = {v: k for k, v in mapping.items()}
    return reverse_mapping.get(source_field, source_field)


def get_application_config() -> Dict[str, Any]:
    """Get application config from datasources config."""
    config = load_datasources_config()
    return config.get("application", {})


VALID_METRICS = {
    "COSINE": Distance.COSINE,
    "EUCLID": Distance.EUCLID,
    "DOT": Distance.DOT,
}

# HNSW Configuration
HNSW_M = int(os.getenv("HNSW_M", "16"))
HNSW_EF_CONSTRUCT = int(os.getenv("HNSW_EF_CONSTRUCT", "100"))

# Storage & Memory Configuration
VECTORS_ON_DISK = os.getenv("VECTORS_ON_DISK", "false").lower() == "true"
HNSW_ON_DISK = os.getenv("HNSW_ON_DISK", "false").lower() == "true"

# Quantization Configuration
ENABLE_QUANTIZATION = os.getenv("ENABLE_QUANTIZATION", "false").lower() == "true"
QUANTIZATION_TYPE = os.getenv("QUANTIZATION_TYPE", "int8")
QUANTIZATION_ALWAYS_RAM = os.getenv("QUANTIZATION_ALWAYS_RAM", "true").lower() == "true"
QUANTIZATION_RESCORE = os.getenv("QUANTIZATION_RESCORE", "true").lower() == "true"


def clean_model_name(model_id: str) -> str:
    """Generate a clean vector name from model ID."""
    name = model_id.split("/")[-1]
    name = name.replace("-en-v1.5", "").replace("-v2", "").replace("-v1", "")
    name = name.replace(".", "_").replace("-", "_")
    return name


def _clean_model_name(model_id: str) -> str:
    """Backward-compatible alias for clean_model_name."""
    return clean_model_name(model_id)
