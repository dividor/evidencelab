"""
LLM Factory for creating LangChain LLM instances with provider-agnostic interface.

This module provides a unified way to instantiate LLMs from different providers
(HuggingFace, OpenAI, Anthropic, etc.) with automatic LangSmith tracing.

Configuration via environment variables:
- LLM_PROVIDER: "huggingface", "openai", "anthropic", or "openai-compatible"
- LLM_MODEL: Model identifier (e.g., "Qwen/Qwen2.5-7B", "gpt-4", "claude-3-opus")
- LLM_TEMPERATURE: Temperature setting (default: 0.7)
- LLM_MAX_TOKENS: Max tokens to generate (default: 500)

Provider-specific keys:
- HUGGINGFACE_API_KEY: For HuggingFace
- OPENAI_API_KEY: For OpenAI or OpenAI-compatible
- ANTHROPIC_API_KEY: For Anthropic
- OPENAI_API_BASE: For OpenAI-compatible (e.g., Groq, Together)
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

from huggingface_hub import InferenceClient
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_openai import ChatOpenAI

from utils.langsmith_util import setup_langsmith_tracing

# Setup LangSmith tracing
setup_langsmith_tracing()

logger = logging.getLogger(__name__)

# Cache LLM instances
_llm_cache: Dict[str, BaseChatModel] = {}


def _resolve_model_key(
    model_key: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve a model key from supported_llms to actual model string,
    provider, and inference_provider.

    Args:
        model_key: Key from supported_llms (e.g., "qwen2.5-7b-instruct") or actual model string

    Returns:
        Tuple of (model_string, provider, inference_provider) or (None, None, None) if not found
    """
    try:
        from pipeline.db import SUPPORTED_LLMS

        # If it's a key in supported_llms, resolve it
        if model_key in SUPPORTED_LLMS:
            llm_config = SUPPORTED_LLMS[model_key]
            return (
                llm_config.get("model"),
                llm_config.get("provider"),
                llm_config.get("inference_provider"),
            )

        # Otherwise, check if it's already a model string (backward compatibility)
        # Look for matching model in supported_llms
        for llm_name, llm_config in SUPPORTED_LLMS.items():
            if llm_config.get("model") == model_key:
                return (
                    llm_config.get("model"),
                    llm_config.get("provider"),
                    llm_config.get("inference_provider"),
                )

        # Not found - might be a direct model string (backward compatibility)
        return (model_key, None, None)
    except Exception:
        # If we can't import or access SUPPORTED_LLMS, return as-is (backward compatibility)
        return (model_key, None, None)


def _get_inference_provider_for_model(model: str, provider: str) -> Optional[str]:
    """
    Look up inference_provider from supported_llms based on model name.

    Args:
        model: Model identifier (e.g., "Qwen/Qwen2.5-7B-Instruct") or
               key (e.g., "qwen2.5-7b-instruct")
        provider: LLM provider (e.g., "huggingface")

    Returns:
        Inference provider string if found, None otherwise
    """
    if provider != "huggingface":
        return None

    try:
        from pipeline.db import SUPPORTED_LLMS

        # First try as a key
        if model in SUPPORTED_LLMS:
            return SUPPORTED_LLMS[model].get("inference_provider")

        # Then try matching model string
        for llm_name, llm_config in SUPPORTED_LLMS.items():
            if llm_config.get("model") == model:
                return llm_config.get("inference_provider")
    except Exception:
        # If we can't import or access SUPPORTED_LLMS, return None
        pass

    return None


def get_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    inference_provider: Optional[str] = None,
) -> BaseChatModel:
    """
    Get or create an LLM instance with automatic LangSmith tracing.

    Args:
        provider: LLM provider ("huggingface", "openai", "anthropic",
                 "openai-compatible"). If None, reads from LLM_PROVIDER
                 env var (default: "huggingface")
        model: Model identifier. If None, reads from LLM_MODEL env var
        temperature: Temperature setting. If None, reads from
                     LLM_TEMPERATURE env var (default: 0.7)
        max_tokens: Max tokens to generate. If None, reads from
                    LLM_MAX_TOKENS env var (default: 500)
        inference_provider: Inference provider for HuggingFace models
                           (e.g., "together", "novita"). If provided,
                           appends ":inference_provider" to model name.

    Returns:
        BaseChatModel: LangChain chat model instance

    Raises:
        ValueError: If provider is unsupported or required API keys are missing

    Examples:
        # Use environment config (default)
        llm = get_llm()

        # Override specific parameters
        llm = get_llm(temperature=0.1, max_tokens=1000)

        # Use a different provider
        llm = get_llm(provider="openai", model="gpt-4-turbo")
    """
    provider = _normalize_provider(provider)
    llm_config = _load_llm_config()
    default_model_key = _normalize_model_key(llm_config.get("model"))
    default_max_tokens = _normalize_default_max_tokens(
        llm_config.get("max_tokens", 500)
    )

    model_key = model or os.getenv("LLM_MODEL") or default_model_key
    model, provider, inference_provider = _resolve_model_settings(
        model_key, provider, inference_provider
    )
    temperature = _resolve_temperature(temperature)
    max_tokens = _resolve_max_tokens(max_tokens, default_max_tokens)

    inference_provider = _resolve_inference_provider(
        inference_provider, model, provider
    )
    cache_key = _build_cache_key(
        provider, model, temperature, max_tokens, inference_provider
    )
    cached = _llm_cache.get(cache_key)
    if cached:
        return cached

    logger.info(
        "Initializing LLM: provider=%s, model=%s, temperature=%s, max_tokens=%s",
        provider,
        model,
        temperature,
        max_tokens,
    )
    llm = _create_llm_for_provider(
        provider, model, temperature, max_tokens, inference_provider
    )
    _llm_cache[cache_key] = llm
    logger.info("✓ LLM initialized and cached: %s/%s", provider, model)
    return llm


def _normalize_provider(provider: Optional[str]) -> str:
    return (provider or os.getenv("LLM_PROVIDER", "huggingface")).lower()


def _load_llm_config() -> Dict[str, Any]:
    from pipeline.db import get_application_config

    app_config = get_application_config()
    llm_config = app_config.get("llm")
    if not llm_config:
        llm_config = app_config.get("ai_summary", {}).get("llm", {})
    return llm_config


def _resolve_model_settings(
    model_key: Optional[str],
    provider: str,
    inference_provider: Optional[str],
) -> Tuple[Optional[str], str, Optional[str]]:
    model = model_key
    if model_key:
        resolved_model, resolved_provider, resolved_inference_provider = (
            _resolve_model_key(model_key)
        )
        if resolved_model:
            model = resolved_model
            if resolved_provider:
                provider = resolved_provider
            if not inference_provider:
                inference_provider = resolved_inference_provider
    return model, provider, inference_provider


def _resolve_temperature(temperature: Optional[float]) -> float:
    if temperature is not None:
        return temperature
    return float(os.getenv("LLM_TEMPERATURE", "0.7"))


def _resolve_max_tokens(max_tokens: Optional[int], default_max_tokens: int) -> int:
    if max_tokens is not None:
        return max_tokens
    return int(os.getenv("LLM_MAX_TOKENS", default_max_tokens))


def _normalize_model_key(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _normalize_default_max_tokens(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 500


def _resolve_inference_provider(
    inference_provider: Optional[str], model: Optional[str], provider: str
) -> Optional[str]:
    if inference_provider or not model:
        return inference_provider
    return _get_inference_provider_for_model(model, provider)


def _build_cache_key(
    provider: str,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    inference_provider: Optional[str],
) -> str:
    if inference_provider:
        return f"{provider}:{model}:{inference_provider}:{temperature}:{max_tokens}"
    return f"{provider}:{model}:{temperature}:{max_tokens}"


def _create_llm_for_provider(
    provider: str,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    inference_provider: Optional[str],
) -> BaseChatModel:
    if provider == "huggingface":
        return _create_huggingface_llm(
            model, temperature, max_tokens, inference_provider
        )
    if provider == "openai":
        return _create_openai_llm(model, temperature, max_tokens)
    if provider == "azure_foundry":
        return _create_azure_foundry_llm(model, temperature, max_tokens)
    if provider == "anthropic":
        return _create_anthropic_llm(model, temperature, max_tokens)
    if provider == "openai-compatible":
        return _create_openai_compatible_llm(model, temperature, max_tokens)
    raise ValueError(
        f"Unsupported LLM_PROVIDER: {provider}. "
        f"Supported: huggingface, openai, azure_foundry, anthropic, openai-compatible"
    )


def _create_huggingface_llm(
    model: str,
    temperature: float,
    max_tokens: int,
    inference_provider: Optional[str] = None,
) -> BaseChatModel:
    """Create HuggingFace LLM instance."""
    api_key = os.getenv("HUGGINGFACE_API_KEY")
    if not api_key:
        raise ValueError(
            "HUGGINGFACE_API_KEY not set. Get your token at: "
            "https://huggingface.co/settings/tokens"
        )

    if inference_provider:
        llm = _create_huggingface_inference_llm(model, api_key, inference_provider)
        if llm:
            return llm
    return _create_huggingface_endpoint_llm(model, api_key, temperature, max_tokens)


def _create_huggingface_inference_llm(
    model: str, api_key: str, inference_provider: str
) -> Optional[BaseChatModel]:
    try:
        inference_client = InferenceClient(
            model=model, token=api_key, provider=inference_provider
        )
        try:
            llm = ChatHuggingFace(client=inference_client)
            logger.info(
                "Using InferenceClient with provider=%s for model=%s",
                inference_provider,
                model,
            )
            return llm
        except (TypeError, ValueError) as exc:
            logger.debug("ChatHuggingFace doesn't accept client parameter: %s", exc)
            raise
    except Exception as exc:
        logger.debug(
            "InferenceClient not compatible with ChatHuggingFace, "
            "using HuggingFaceEndpoint instead: %s",
            exc,
        )
        return None


def _create_huggingface_endpoint_llm(
    model: str, api_key: str, temperature: float, max_tokens: int
) -> BaseChatModel:
    llm_endpoint = HuggingFaceEndpoint(
        repo_id=model,
        huggingfacehub_api_token=api_key,
        temperature=temperature,
        max_new_tokens=max_tokens,
        timeout=240,
    )
    return ChatHuggingFace(llm=llm_endpoint)


def _create_azure_foundry_llm(
    model: str, temperature: float, max_tokens: int
) -> BaseChatModel:
    """Create Azure Foundry LLM instance."""
    api_key = os.getenv("AZURE_FOUNDRY_KEY")
    endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
    api_version = os.getenv("AZURE_FOUNDRY_API_VERSION", "2024-02-15-preview")

    if not api_key:
        raise ValueError("Azure Foundry API key not set. Set AZURE_FOUNDRY_KEY")

    if not endpoint:
        raise ValueError("Azure Foundry endpoint not set. Set AZURE_FOUNDRY_ENDPOINT")

    # Construct the base URL for Azure Foundry
    # Format: https://{resource}.openai.azure.com/openai/deployments/{deployment}
    azure_base = endpoint.rstrip("/")
    if "/openai/deployments" not in azure_base:
        azure_base = f"{azure_base}/openai/deployments/{model}"

    return ChatOpenAI(
        model=model,  # Deployment name
        api_key=api_key,
        base_url=azure_base,
        default_query={"api-version": api_version},
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_openai_llm(
    model: str, temperature: float, max_tokens: int
) -> BaseChatModel:
    """Create OpenAI LLM instance."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not set. Get your token at: "
            "https://platform.openai.com/api-keys"
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
    )


def _create_anthropic_llm(
    model: str, temperature: float, max_tokens: int
) -> BaseChatModel:
    """Create Anthropic LLM instance."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Get your token at: "
            "https://console.anthropic.com/settings/keys"
        )

    return ChatAnthropic(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
    )


def _create_openai_compatible_llm(
    model: str, temperature: float, max_tokens: int
) -> BaseChatModel:
    """Create OpenAI-compatible LLM instance (Groq, Together, etc.)."""
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE")

    if not api_key:
        raise ValueError("OPENAI_API_KEY not set for openai-compatible provider")

    if not base_url:
        raise ValueError(
            "OPENAI_API_BASE not set for openai-compatible provider. "
            "Example: https://api.groq.com/openai/v1"
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=base_url,
    )


def clear_llm_cache():
    """Clear the LLM instance cache. Useful for testing or config changes."""
    global _llm_cache
    _llm_cache = {}
    logger.info("LLM cache cleared")
