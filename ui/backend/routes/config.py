from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

import pipeline.db as pipeline_db
from pipeline.db import (
    DB_VECTORS,
    DENSE_VECTOR_NAME,
    SUPPORTED_LLMS,
    SUPPORTED_RERANK_MODELS,
    UI_MODEL_COMBOS,
)
from ui.backend.schemas import LLMConfig, ModelComboConfig, ModelConfig
from ui.backend.utils.app_limits import get_rate_limits, limiter
from ui.backend.utils.app_state import get_pg_for_source

_RATE_LIMIT_SEARCH, RATE_LIMIT_DEFAULT, _RATE_LIMIT_AI = get_rate_limits()
router = APIRouter()


@router.get("/")
@limiter.limit(RATE_LIMIT_DEFAULT)
def root(request: Request):
    """API root"""
    return {
        "name": "Humanitarian Evaluation Search API",
        "version": "1.0.0",
        "endpoints": {
            "/search": "Semantic search",
            "/facets": "Get filter facets",
            "/document/{doc_id}": "Get document metadata",
            "/pdf/{doc_id}": "Serve PDF file",
            "/highlight/{doc_id}": "Get highlight bounding boxes",
            "/highlight/{doc_id}": "Get highlight bounding boxes",
            "/ai-summary": "Generate AI summary of search results",
            "/config/models": "Get available embedding models",
            "/config/llms": "Get available LLM models",
            "/config/model-combos": "Get UI model combos",
        },
    }


@router.get("/config/models", response_model=List[ModelConfig])
def get_config_models():
    """Get list of available embedding models."""
    models_list = []

    for name, config in DB_VECTORS.items():
        if config.get("enabled", False):
            # Create a nice description
            source = config.get("source", "huggingface")

            # Format description for UI
            if source == "azure_foundry":
                desc = f"Azure Foundry ({name})"
            else:
                desc = f"{name} ({source})"

            models_list.append(
                ModelConfig(
                    name=name, description=desc, is_default=(name == DENSE_VECTOR_NAME)
                )
            )

    return models_list


@router.get("/config/llms", response_model=List[LLMConfig])
def get_config_llms():
    """Get list of available LLM models."""
    llms_list = []

    for name, config in SUPPORTED_LLMS.items():
        llms_list.append(
            LLMConfig(
                name=name,
                model=config.get("model", ""),
                provider=config.get("provider", "huggingface"),
                inference_provider=config.get("inference_provider"),
            )
        )

    return llms_list


def _location_from_source(source: Optional[str]) -> str:
    if not source:
        return "Local"
    if source in {"azure_foundry", "openai", "api"}:
        return "API"
    return "Local"


def _location_from_llm(model_name: Optional[str]) -> str:
    if not model_name:
        return "Local"
    llm_config = SUPPORTED_LLMS.get(model_name, {})
    provider = llm_config.get("provider")
    inference_provider = llm_config.get("inference_provider")
    if provider or inference_provider:
        return "API"
    return _location_from_source(provider)


def _resolve_embedding_model_id(
    combo_name: str, embedding_key: str
) -> tuple[str, Dict[str, Any]]:
    embedding_config = DB_VECTORS.get(embedding_key)
    if not embedding_config:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Embedding model '{embedding_key}' not found in DB_VECTORS "
                f"for combo '{combo_name}'"
            ),
        )
    embedding_model_id = embedding_config.get("model_id")
    if not embedding_model_id:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Embedding model '{embedding_key}' missing model_id "
                f"for combo '{combo_name}'"
            ),
        )
    return embedding_model_id, embedding_config


def _resolve_optional_model_key(config_value: Any) -> Optional[str]:
    if isinstance(config_value, dict):
        return config_value.get("model")
    return None


def _resolve_reranker_location(reranker_key: Optional[str]) -> str:
    reranker_config = SUPPORTED_RERANK_MODELS.get(reranker_key, {})
    reranker_provider = reranker_config.get("provider")
    reranker_source = reranker_config.get("source")
    return "API" if reranker_provider or reranker_source == "huggingface" else "Local"


def _build_model_combo(combo_name: str, combo: Dict[str, Any]) -> Dict[str, Any]:
    embedding_key = combo.get("embedding_model")
    embedding_model_id, embedding_config = _resolve_embedding_model_id(
        combo_name, embedding_key
    )
    summarization_key = _resolve_optional_model_key(combo.get("summarization_model"))
    semantic_key = _resolve_optional_model_key(combo.get("semantic_highlighting_model"))
    reranker_key = combo.get("reranker_model")
    return {
        **combo,
        "embedding_model_id": embedding_model_id,
        "embedding_model_location": _location_from_source(
            embedding_config.get("source")
        ),
        "sparse_model_location": "Local" if combo.get("sparse_model") else None,
        "summarization_model_location": _location_from_llm(summarization_key),
        "semantic_highlighting_location": _location_from_llm(semantic_key),
        "reranker_model_location": _resolve_reranker_location(reranker_key),
    }


@router.get("/config/model-combos", response_model=Dict[str, ModelComboConfig])
def get_config_model_combos():
    """Get list of available model combos for the UI."""
    combos_with_ids: Dict[str, Dict[str, Any]] = {}
    for combo_name, combo in UI_MODEL_COMBOS.items():
        combos_with_ids[combo_name] = _build_model_combo(combo_name, combo)
    return combos_with_ids


@router.get("/config/datasources")
async def get_datasources_config():
    """Get datasources configuration for UI, enriched with document totals."""
    config = pipeline_db.load_datasources_config()
    datasources = config.get("datasources", {})
    for name, ds_config in datasources.items():
        data_subdir = ds_config.get("data_subdir")
        if not data_subdir:
            continue
        try:
            pg = get_pg_for_source(data_subdir)
            status_counts = pg.fetch_status_counts()
            ds_config["total_documents"] = sum(status_counts.values())
        except Exception:
            pass
    return datasources


@router.get("/health")
def health():
    """Health check"""
    return {"status": "healthy"}
