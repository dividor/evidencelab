import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

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
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source

logger = logging.getLogger(__name__)

# Parse USER_MODULE mode: off | on_passive | on_active
# Backwards compatible: true/1/yes → on_active, false/0/no → off
_UM_RAW = os.environ.get("USER_MODULE", "off").lower()
if _UM_RAW in ("1", "true", "yes", "on_active"):
    _USER_MODULE_MODE = "on_active"
elif _UM_RAW in ("on_passive",):
    _USER_MODULE_MODE = "on_passive"
else:
    _USER_MODULE_MODE = "off"
_USER_MODULE = _USER_MODULE_MODE != "off"

# Conditional imports for user module — resolved at module load time so
# FastAPI can wire up Depends() correctly.
if _USER_MODULE:
    from ui.backend.auth.db import get_async_session as _get_session_dep
    from ui.backend.auth.users import optional_current_user as _resolve_user_dep
    from ui.backend.services.permissions import (
        filter_datasources,
        get_user_datasource_keys,
    )
else:

    async def _noop_user():  # type: ignore[misc]
        return None

    async def _noop_session():  # type: ignore[misc]
        return None

    _resolve_user_dep = _noop_user  # type: ignore[assignment]
    _get_session_dep = _noop_session  # type: ignore[assignment]

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
async def get_datasources_config(
    request: Request,
    current_user=Depends(_resolve_user_dep),
    session=Depends(_get_session_dep),
):
    """Get datasources configuration for UI, enriched with document totals.

    When the user module is enabled, the response is filtered to only include
    datasources the authenticated user has permission to access.
    """
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

    # Filter datasources by user permissions when user module is active.
    # on_active: deny-by-default — unauthenticated users see nothing.
    # on_passive: unauthenticated users see all datasources; authenticated
    #   non-superusers are filtered by group permissions.
    if _USER_MODULE:
        try:
            if current_user is None:
                if _USER_MODULE_MODE == "on_active":
                    datasources = {}
                # on_passive: unauthenticated users see all datasources
            elif not current_user.is_superuser:
                allowed = await get_user_datasource_keys(session, current_user.id)
                datasources = filter_datasources(datasources, allowed)
        except Exception:
            logger.exception("Permission check failed — denying datasource access")
            datasources = {}  # Deny by default on error

    return datasources


@router.get("/config/datasources/{key}/payload-fields")
async def get_datasource_payload_fields(
    key: str,
    request: Request,
    current_user=Depends(_resolve_user_dep),
    session=Depends(_get_session_dep),
):
    """Return all payload field names found on chunk records for a datasource.

    Queries both the Qdrant payload index schema *and* an actual point record
    so that unindexed ``src_*`` / ``tag_*`` fields are included too.
    """
    config = pipeline_db.load_datasources_config()
    datasources = config.get("datasources", {})
    ds_config = datasources.get(key)
    if not ds_config:
        raise HTTPException(status_code=404, detail=f"Datasource '{key}' not found")

    data_subdir = ds_config.get("data_subdir", key)

    # Permission check when user module is active
    if _USER_MODULE:
        if current_user is None and _USER_MODULE_MODE == "on_active":
            raise HTTPException(status_code=401, detail="Authentication required")
        if current_user and not current_user.is_superuser:
            allowed = await get_user_datasource_keys(session, current_user.id)
            if key not in allowed:
                raise HTTPException(status_code=403, detail="Access denied")

    field_set: set[str] = set()
    try:
        db = get_db_for_source(data_subdir)

        # 1. Indexed fields from schema
        collection_info = db.client.get_collection(db.chunks_collection)
        if collection_info.payload_schema:
            field_set.update(collection_info.payload_schema.keys())

        # 2. Sample one actual point to capture unindexed payload keys
        points, _ = db.client.scroll(
            collection_name=db.chunks_collection,
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if points:
            field_set.update(points[0].payload.keys())
    except Exception:
        logger.exception("Failed to fetch payload fields for '%s'", key)

    return {"fields": sorted(field_set)}


@router.get("/config/auth-status")
def get_auth_status():
    """Return the user module mode (for frontend feature flag)."""
    return {
        "user_module_enabled": _USER_MODULE,
        "user_module_mode": _USER_MODULE_MODE,
    }


@router.get("/health")
def health():
    """Health check"""
    return {"status": "healthy"}
