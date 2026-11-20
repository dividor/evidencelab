"""Limits on the model settings a request may ask for.

The AI routes take a model and an output-token budget from the request (the
web interface sends the model combo's settings). Anyone holding the browser's
public key could otherwise name a model that is not offered, or ask for a huge
output, and run up the bill. A request may only use:

- a model listed in config.json (``supported_llms``, by key or model id), and
- at most as many output tokens as config.json allows for that model: the
  largest ``max_tokens`` among its ``supported_llms`` entry and the model
  combo stages that use it, or, for a model with no value of its own, the
  largest value any combo stage sets.

Both limits come from config.json, so they change with it.
"""

from typing import Any, Iterable, Optional

from fastapi import HTTPException

from pipeline.db import config as db_config

_COMBO_STAGES = (
    "summarization_model",
    "semantic_highlighting_model",
    "assistant_model",
)


def _stage_settings() -> Iterable[dict]:
    for combo in db_config.UI_MODEL_COMBOS.values():
        for stage in _COMBO_STAGES:
            settings = combo.get(stage)
            if isinstance(settings, dict):
                yield settings


def _names_for(key: str, entry: dict) -> set:
    names = {key}
    if entry.get("model"):
        names.add(str(entry["model"]))
    return names


def _matching_entry(model: str) -> Optional[tuple[str, dict]]:
    for key, entry in db_config.SUPPORTED_LLMS.items():
        if model in _names_for(key, entry):
            return key, entry
    return None


def max_output_tokens(model: Optional[str]) -> int:
    """The largest output-token budget config.json allows for *model*."""
    all_values = [
        int(s["max_tokens"]) for s in _stage_settings() if s.get("max_tokens")
    ]
    match = _matching_entry(model) if model else None
    if match is None:
        return max(all_values, default=0)
    key, entry = match
    names = _names_for(key, entry)
    own = [
        int(s["max_tokens"])
        for s in _stage_settings()
        if s.get("max_tokens") and s.get("model") in names
    ]
    if entry.get("max_tokens"):
        own.append(int(entry["max_tokens"]))
    return max(own) if own else max(all_values, default=0)


def check_requested_llm(model: Optional[str], max_tokens: Optional[int]) -> None:
    """Refuse a model not in config.json, or more output tokens than it allows.

    ``model`` None means the configured default, which is always allowed.
    Raises HTTPException(400) with a message that names the limit.
    """
    if model and _matching_entry(model) is None:
        raise HTTPException(
            status_code=400, detail="Model is not available on this server"
        )
    if max_tokens is None:
        return
    ceiling = max_output_tokens(model)
    if max_tokens < 1 or max_tokens > ceiling:
        raise HTTPException(
            status_code=400,
            detail=f"max_tokens must be between 1 and {ceiling} for this model",
        )


def check_model_config(config: Any) -> None:
    """``check_requested_llm`` for a request's model-config object, if present."""
    if config is not None:
        check_requested_llm(
            getattr(config, "model", None), getattr(config, "max_tokens", None)
        )
