"""
LLM Factory for creating LangChain LLM instances with provider-agnostic interface.

This module provides a unified way to instantiate LLMs from different providers
(HuggingFace, OpenAI, Anthropic, etc.) with tracing per utils.tracing.

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

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from pydantic import SecretStr

from utils.tracing import get_trace_recorder

# Resolve the tracing backend up front so LangChain sees its environment
# (e.g. the LANGCHAIN_* variables LangSmith needs) before any LLM is built.
get_trace_recorder()

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
    Get or create an LLM instance (traced per the configured tracing backend).

    Args:
        provider: LLM provider ("huggingface", "openai", "anthropic",
                 "azure_foundry", "google_vertex", "openai-compatible",
                 "aws_bedrock").
                 Resolved from model config or LLM_PROVIDER env var.
                 Raises ValueError if no provider can be determined.
        model: Model identifier. If None, reads from LLM_MODEL env var
        temperature: Temperature setting. If None, reads from
                     LLM_TEMPERATURE env var (default: 0.7)
        max_tokens: Max tokens to generate. If None, reads from
                    LLM_MAX_TOKENS env var (default: 500)
        inference_provider: Inference provider for HuggingFace models
                           (e.g., "scaleway", "together"). If provided,
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
    llm_config = _load_llm_config()
    default_model_key = _normalize_model_key(llm_config.get("model"))
    default_max_tokens = _normalize_default_max_tokens(
        llm_config.get("max_tokens", 500)
    )

    model_key = model or os.getenv("LLM_MODEL") or default_model_key
    # Resolve model settings first (may provide the provider from config)
    initial_provider = provider or os.getenv("LLM_PROVIDER") or ""
    model, provider, inference_provider = _resolve_model_settings(
        model_key, initial_provider, inference_provider
    )
    # Ensure we have a valid provider after resolution
    if not provider:
        raise ValueError(
            f"No LLM provider found for model '{model_key}'. "
            f"Set 'provider' in config.json supported_llms entries "
            f"or set LLM_PROVIDER environment variable."
        )
    provider = provider.lower()
    temperature = (
        _resolve_temperature(temperature) if _supports_temperature(model_key) else None
    )
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


def _supports_temperature(model_key: Optional[str]) -> bool:
    """False for a ``supported_llms`` entry marked ``"supports_temperature":
    false``: that model refuses a temperature, so none is sent. Models config.json
    doesn't list, and entries without the flag, take one."""
    from pipeline.db import config as db_config

    key = supported_llm_key(model_key) if model_key else None
    if key is None:
        return True
    return bool(db_config.SUPPORTED_LLMS[key].get("supports_temperature", True))


def _resolve_max_tokens(max_tokens: Optional[int], default_max_tokens: int) -> int:
    if max_tokens is not None:
        return max_tokens
    return int(os.getenv("LLM_MAX_TOKENS", default_max_tokens))


def _normalize_model_key(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def default_model_name() -> Optional[str]:
    """The model a ``get_llm()`` call that names none uses.

    The ``LLM_MODEL`` env var, then the ``llm`` model in config.json's
    ``application`` section (as ``get_llm`` reads them); None when neither
    is set.
    """
    return os.getenv("LLM_MODEL") or _normalize_model_key(
        _load_llm_config().get("model")
    )


def supported_llm_key(name: str) -> Optional[str]:
    """The ``supported_llms`` key that *name* stands for, or None.

    *name* may be the key itself or the provider's model id from an entry
    (``us.amazon.nova-2-lite-v1:0`` for ``nova-2-lite``). A key wins over a
    model id, and of several entries with the same model id the first wins,
    the same order ``get_llm`` resolves them in.
    """
    from pipeline.db import config as db_config

    if name in db_config.SUPPORTED_LLMS:
        return name
    for key, entry in db_config.SUPPORTED_LLMS.items():
        if entry.get("model") == name:
            return key
    return None


def resolve_effective_model_key(model: Optional[str]) -> Optional[str]:
    """Return the ``supported_llms`` key of the model a ``get_llm(model=...)``
    call uses.

    Usage is priced by this key (``ui.backend.utils.llm_costs``), so a call
    is labelled with it however the caller named the model: by key, by the
    provider's model id, or not at all (the default model, see
    :func:`default_model_name`). A name config.json does not list is
    returned as given, since that is the model ``get_llm`` then calls; it has
    no price. None when no model is named and no default is set.
    """
    name = model or default_model_name()
    if not name:
        return None
    return supported_llm_key(name) or name


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
    temperature: Optional[float],
    max_tokens: int,
    inference_provider: Optional[str],
) -> str:
    if inference_provider:
        return f"{provider}:{model}:{inference_provider}:{temperature}:{max_tokens}"
    return f"{provider}:{model}:{temperature}:{max_tokens}"


def _create_llm_for_provider(
    provider: str,
    model: Optional[str],
    temperature: Optional[float],
    max_tokens: int,
    inference_provider: Optional[str],
) -> BaseChatModel:
    assert model is not None, f"model must be set for provider '{provider}'"
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
    if provider == "google_vertex":
        return _create_google_vertex_llm(model, temperature, max_tokens)
    if provider == "openai-compatible":
        return _create_openai_compatible_llm(model, temperature, max_tokens)
    if provider == "aws_bedrock":
        return _create_aws_bedrock_llm(model, temperature, max_tokens)
    raise ValueError(
        f"Unsupported LLM_PROVIDER: {provider}. "
        f"Supported: huggingface, openai, azure_foundry, anthropic, "
        f"google_vertex, openai-compatible, aws_bedrock"
    )


# Hugging Face's router speaks the OpenAI chat API and routes ``<model>:<provider>``
# itself (``<model>`` alone lets it choose a provider).
HF_ROUTER_BASE_URL = "https://router.huggingface.co/v1"


def _create_huggingface_llm(
    model: str,
    temperature: Optional[float],
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

    return _create_huggingface_router_llm(
        model, api_key, temperature, max_tokens, inference_provider
    )


def _create_huggingface_router_llm(
    model: str,
    api_key: str,
    temperature: Optional[float],
    max_tokens: int,
    inference_provider: Optional[str] = None,
) -> BaseChatModel:
    """Create a Hugging Face chat model called through the router's OpenAI API.

    ``inference_provider`` pins the router to one provider (e.g. "groq"); a
    provider that stops serving the model fails the call rather than moving
    on. Without it the router chooses a provider itself.

    huggingface_hub's own client is not used: it looks the provider up in the
    model API's ``inferenceProviderMapping``, which since 2026-11-24 comes back
    empty for every model (huggingface_hub 0.36.2 and 2.4.0 alike), so every
    call failed with "Model ... is not supported by provider ...". The router
    itself still serves those models.
    """
    from langchain_openai import ChatOpenAI

    routed_model = f"{model}:{inference_provider}" if inference_provider else model
    settings: Dict[str, Any] = {
        "model": routed_model,
        "api_key": SecretStr(api_key),
        "base_url": HF_ROUTER_BASE_URL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": 240,
        # Streamed calls (search summaries) report their token usage too.
        "stream_usage": True,
    }
    if inference_provider:
        logger.info(
            "Using Hugging Face provider=%s for model=%s", inference_provider, model
        )
    return ChatOpenAI(**settings)


def _create_azure_foundry_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create Azure Foundry LLM instance."""
    from langchain_openai import ChatOpenAI

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

    return ChatOpenAI(  # type: ignore[call-arg]
        model=model,  # Deployment name
        api_key=SecretStr(api_key),
        base_url=azure_base,
        default_query={"api-version": api_version},
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_aws_bedrock_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create an Amazon Bedrock chat model (Converse API).

    ``model`` is a Bedrock model or inference profile ID, for example
    ``us.amazon.nova-2-lite-v1:0``. Credentials and region come from the
    standard AWS sources (environment, profile or ECS task role).
    """
    from langchain_aws import ChatBedrockConverse

    from pipeline.utilities.aws_bedrock_client import bedrock_region

    return ChatBedrockConverse(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        region_name=bedrock_region(),
    )


def _create_openai_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create OpenAI LLM instance."""
    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not set. Get your token at: "
            "https://platform.openai.com/api-keys"
        )

    return ChatOpenAI(  # type: ignore[call-arg]
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=SecretStr(api_key),
    )


def _create_anthropic_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create Anthropic LLM instance."""
    from langchain_anthropic import ChatAnthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Get your token at: "
            "https://console.anthropic.com/settings/keys"
        )

    return ChatAnthropic(  # type: ignore[call-arg]
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=SecretStr(api_key),
    )


def _create_google_vertex_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create Google Vertex AI LLM instance."""
    from langchain_google_vertexai import ChatVertexAI

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and os.path.exists(creds_path):
            with open(creds_path, encoding="utf-8") as f:
                creds_data = json.load(f)
                project = creds_data.get("project_id")
    if not project:
        raise ValueError(
            "Google Cloud project not found. Set GOOGLE_CLOUD_PROJECT or "
            "GOOGLE_APPLICATION_CREDENTIALS pointing to a service account JSON."
        )
    # Gemini 3 models are served from the global location; a new project got
    # 404 for them from us-central1.
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    # Gemini 2.5 and Gemini 3 Flash models "think" by default, which consumes
    # output tokens from max_output_tokens and truncates the visible response
    # (gemini-3.8-flash at 500 tokens: 406 thinking, answer cut off).
    # Disable thinking so all output tokens are used for the actual response.
    kwargs: dict[str, Any] = {}
    if "2.5" in model or (model.startswith("gemini-3") and "flash" in model):
        kwargs["thinking_budget"] = 0
    # Throttle requests to stay within GCP Vertex AI per-minute quotas.
    # VERTEX_AI_RPM env var controls requests-per-minute (default 5).
    rpm = int(os.getenv("VERTEX_AI_RPM", "5"))
    rate_limiter = InMemoryRateLimiter(
        requests_per_second=rpm / 60.0,
        check_every_n_seconds=0.5,
        max_bucket_size=rpm,
    )
    return ChatVertexAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        project=project,
        location=location,
        rate_limiter=rate_limiter,
        **kwargs,
    )


def _create_openai_compatible_llm(
    model: str, temperature: Optional[float], max_tokens: int
) -> BaseChatModel:
    """Create OpenAI-compatible LLM instance (Groq, Together, etc.)."""
    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE")

    if not api_key:
        raise ValueError("OPENAI_API_KEY not set for openai-compatible provider")

    if not base_url:
        raise ValueError(
            "OPENAI_API_BASE not set for openai-compatible provider. "
            "Example: https://api.groq.com/openai/v1"
        )

    return ChatOpenAI(  # type: ignore[call-arg]
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=SecretStr(api_key),
        base_url=base_url,
    )


def message_text(message: BaseMessage) -> str:
    """The text of a chat model's reply.

    Providers return ``content`` either as a string (OpenAI, Azure Foundry,
    Hugging Face) or as a list of content blocks (Amazon Bedrock when
    streaming, Gemini with tool calls). ``str(message.content)`` turns a block
    list into its Python repr, which reached users as
    ``[{'type': 'text', 'text': 'The most', ...}]``. LangChain's ``text``
    property joins a list's text blocks; string content is returned as it is.
    """
    content = message.content
    if isinstance(content, str):
        return content
    return str(message.text)


def clear_llm_cache():
    """Clear the LLM instance cache. Useful for testing or config changes."""
    global _llm_cache
    _llm_cache = {}
    logger.info("LLM cache cleared")
