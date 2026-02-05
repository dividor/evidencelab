"""
Configuration validator for LLM model references.

Ensures that model references in pipeline and UI configs use keys from supported_llms.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_llm_model_reference(
    model_key: str, supported_llms: Dict[str, Any], config_path: str = ""
) -> bool:
    """
    Validate that a model key exists in supported_llms.

    Args:
        model_key: The model key to validate (e.g., "qwen2.5-7b-instruct")
        supported_llms: Dictionary of supported LLMs from config
        config_path: Path in config for error messages
                     (e.g., "datasources.wfp.pipeline.summarize.llm_model")

    Returns:
        True if valid, False otherwise
    """
    if not model_key:
        logger.error(f"Empty model key in {config_path}")
        return False

    if model_key not in supported_llms:
        logger.error(
            f"Model key '{model_key}' not found in supported_llms. "
            f"Available keys: {list(supported_llms.keys())}. "
            f"Config path: {config_path}"
        )
        return False

    return True


def resolve_llm_model_config(
    model_key: str,
    supported_llms: Dict[str, Any],
    override_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolve a model key to full LLM configuration.

    Args:
        model_key: Key from supported_llms (e.g., "qwen2.5-7b-instruct")
        supported_llms: Dictionary of supported LLMs from config
        override_params: Optional parameters to override (temperature, max_tokens, etc.)

    Returns:
        Full LLM configuration dictionary with model, provider, inference_provider, etc.
    """
    if model_key not in supported_llms:
        raise ValueError(
            f"Model key '{model_key}' not found in supported_llms. "
            f"Available keys: {list(supported_llms.keys())}"
        )

    model_config = supported_llms[model_key].copy()

    # Apply overrides if provided
    if override_params:
        model_config.update(override_params)

    return model_config


def validate_all_llm_references(config: Dict[str, Any]) -> List[str]:
    """
    Validate all LLM model references in the config.

    Args:
        config: Full configuration dictionary

    Returns:
        List of error messages (empty if all valid)
    """
    errors: List[str] = []
    supported_llms = config.get("supported_llms", {})

    if not supported_llms:
        errors.append("No 'supported_llms' section found in config.json")
        return errors

    app_llm = config.get("application", {}).get("ai_summary", {}).get("llm", {})
    _validate_model_key(
        app_llm.get("model"),
        supported_llms,
        "application.ai_summary.llm.model",
        errors,
    )

    datasources = config.get("datasources", {})
    for datasource_name, datasource_config in datasources.items():
        pipeline = datasource_config.get("pipeline", {})
        _validate_pipeline_llm_configs(
            datasource_name, pipeline, supported_llms, errors
        )

    return errors


def validate_ui_model_combos(config: Dict[str, Any]) -> List[str]:
    """
    Validate UI model combo references against supported model lists.

    Args:
        config: Full configuration dictionary

    Returns:
        List of error messages (empty if all valid)
    """
    errors: List[str] = []
    combos = config.get("ui_model_combos", {})
    if not combos:
        return errors

    supported_embeddings = config.get("supported_embedding_models", {})
    supported_llms = config.get("supported_llms", {})
    supported_rerank = config.get("supported_rerank_models", {})

    for combo_name, combo in combos.items():
        errors.extend(
            _validate_ui_combo(
                combo_name,
                combo,
                supported_embeddings,
                supported_llms,
                supported_rerank,
            )
        )

    return errors


def _validate_ui_combo(
    combo_name: str,
    combo: Dict[str, Any],
    supported_embeddings: Dict[str, Any],
    supported_llms: Dict[str, Any],
    supported_rerank: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    embedding_key = combo.get("embedding_model")
    sparse_key = combo.get("sparse_model")
    reranker_key = combo.get("reranker_model")
    summarization_key = _extract_model_key(combo.get("summarization_model"))
    semantic_key = _extract_model_key(combo.get("semantic_highlighting_model"))

    if embedding_key not in supported_embeddings:
        errors.append(
            f"ui_model_combos.{combo_name}.embedding_model: "
            f"'{embedding_key}' not in supported_embedding_models"
        )
    if sparse_key and sparse_key != "bm25":
        errors.append(
            f"ui_model_combos.{combo_name}.sparse_model: "
            f"'{sparse_key}' is not supported"
        )

    errors.extend(
        _validate_ui_combo_model_key(
            combo_name,
            "summarization_model",
            summarization_key,
            supported_llms,
        )
    )
    errors.extend(
        _validate_ui_combo_model_key(
            combo_name,
            "semantic_highlighting_model",
            semantic_key,
            supported_llms,
        )
    )

    if reranker_key not in supported_rerank:
        errors.append(
            f"ui_model_combos.{combo_name}.reranker_model: "
            f"'{reranker_key}' not in supported_rerank_models"
        )
    return errors


def _extract_model_key(model_config: Any) -> Optional[str]:
    if isinstance(model_config, dict):
        return model_config.get("model")
    return model_config


def _validate_ui_combo_model_key(
    combo_name: str,
    field_name: str,
    model_key: Optional[str],
    supported_llms: Dict[str, Any],
) -> List[str]:
    if not model_key:
        return [f"ui_model_combos.{combo_name}.{field_name}.model: missing model key"]
    if model_key not in supported_llms:
        return [
            f"ui_model_combos.{combo_name}.{field_name}.model: "
            f"'{model_key}' not in supported_llms"
        ]
    return []


def _validate_model_key(
    model_key: Optional[str],
    supported_llms: Dict[str, Any],
    path: str,
    errors: List[str],
) -> None:
    if not model_key:
        return
    if not validate_llm_model_reference(model_key, supported_llms, path):
        errors.append(f"{path}: '{model_key}' not in supported_llms")


def _validate_pipeline_llm_configs(
    datasource_name: str,
    pipeline: Dict[str, Any],
    supported_llms: Dict[str, Any],
    errors: List[str],
) -> None:
    checks = [
        ("summarize", None, "summarize"),
        ("tag", None, "tag"),
    ]

    for section, subsection, label in checks:
        section_config = pipeline.get(section, {})
        if not section_config.get("enabled"):
            continue
        if subsection:
            section_config = section_config.get(subsection, {})
        llm_model = section_config.get("llm_model", {})
        if not isinstance(llm_model, dict):
            continue
        model_key = llm_model.get("model")
        if not model_key:
            continue
        path = _build_pipeline_llm_path(datasource_name, section, subsection, label)
        _validate_model_key(model_key, supported_llms, path, errors)


def _build_pipeline_llm_path(
    datasource_name: str, section: str, subsection: Optional[str], label: str
) -> str:
    if subsection:
        return (
            f"datasources.{datasource_name}.pipeline.{section}."
            f"{label}.llm_model.model"
        )
    return f"datasources.{datasource_name}.pipeline.{label}.llm_model.model"
