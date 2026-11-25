"""Estimated environmental footprint of one LLM call, from EcoLogits.

EcoLogits (https://ecologits.ai, MPL-2.0) estimates a text generation call's
energy use, greenhouse gas emissions and water use from the model's size and
the number of tokens it generated, for the data centre's electricity mix. It
gives each figure as a range, because model sizes, hardware and data-centre
efficiency are themselves ranges.

This module maps a ``supported_llms`` key (the name a call's usage is recorded
under, as for its cost in ``llm_costs``) to an EcoLogits model, and returns
``None`` for a model EcoLogits doesn't cover: Amazon Nova, for example, has no
published size, and embedding and rerank models are out of its scope. Nothing
is guessed for those; the caller counts their output tokens as unestimated.

A ``supported_llms`` entry in config.json may set:

- ``ecologits``: ``{"provider": ..., "model": ...}``, the EcoLogits model to
  use instead of this module's table (or for a model the table lacks);
- ``electricity_mix_zone``: where the model runs, as an EcoLogits zone code
  (ISO 3166-1 alpha-3 country such as ``IRL``, or ``WOR`` for the world).
  Without it, EcoLogits' own default for the provider applies (the USA for
  Anthropic, OpenAI and Google).

``validate_footprint_settings`` checks those settings at start-up, so a typo
stops the api instead of leaving every call unestimated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# supported_llms key -> (EcoLogits provider, EcoLogits model name). Each entry
# is checked against EcoLogits' model repository by the unit tests.
ECOLOGITS_MODELS: Mapping[str, Tuple[str, str]] = {
    # Azure Foundry (OpenAI models)
    "gpt-4.1-mini": ("openai", "gpt-4.1-mini"),
    # Google Vertex (Gemini)
    "gemini-2.5-flash": ("google_genai", "gemini-2.5-flash"),
    "gemini-2.5-pro": ("google_genai", "gemini-2.5-pro"),
    "gemini-3.8-flash": ("google_genai", "gemini-3.8-flash"),
    # Anthropic's models, also when called through Amazon Bedrock
    "haiku-4.5": ("anthropic", "claude-haiku-4-5"),
    "sonnet-4.6": ("anthropic", "claude-sonnet-4-6"),
    "sonnet-5.5": ("anthropic", "claude-sonnet-5-5"),
    # Hugging Face (open-weights)
    "llama-3.1-8b-instruct": (
        "huggingface_hub",
        "meta-llama/Meta-Llama-3.1-8B-Instruct",
    ),
    # EcoLogits has no Llama 3.3 70B entry. Llama 3.3 70B has the same
    # architecture (LlamaForCausalLM) and exactly the same parameter count as
    # Llama 3.1 70B (70,553,706,496 each, Hugging Face API, 2026-11-25), and
    # EcoLogits estimates from the parameter count, so its 3.1 entry gives
    # what its method would give for 3.3. The serving hardware is unknown.
    "llama-3.3-70b-instruct": (
        "huggingface_hub",
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
    ),
}

# The request latency handed to EcoLogits. It takes the smaller of this and
# its own estimate of the generation time (from the model's size and the
# tokens generated); calls are not timed here, so its estimate is used.
_UNMEASURED_LATENCY = math.inf

Range = Tuple[float, float]


@dataclass(frozen=True)
class Footprint:
    """One call's estimated footprint, each as (min, max)."""

    energy_kwh: Range
    gwp_kgco2eq: Range
    water_l: Range


def _llm_settings(model_key: str) -> Dict[str, Any]:
    from pipeline.db import config as db_config

    return db_config.SUPPORTED_LLMS.get(model_key) or {}


def ecologits_model(model_key: Optional[str]) -> Optional[Tuple[str, str]]:
    """(provider, model) EcoLogits estimates ``model_key`` as, or None."""
    if not model_key:
        return None
    override = _llm_settings(model_key).get("ecologits")
    if override:
        return (str(override["provider"]), str(override["model"]))
    return ECOLOGITS_MODELS.get(model_key)


def electricity_mix_zone(model_key: str) -> Optional[str]:
    """The zone set for ``model_key`` in config.json, or None for EcoLogits' default."""
    zone = _llm_settings(model_key).get("electricity_mix_zone")
    return str(zone) if zone else None


def _as_range(value: Any) -> Range:
    """EcoLogits gives a float or a range with ``min`` and ``max``."""
    if hasattr(value, "min") and hasattr(value, "max"):
        return (float(value.min), float(value.max))
    return (float(value), float(value))


def estimate_footprint(
    model_key: Optional[str], completion_tokens: Optional[int]
) -> Optional[Footprint]:
    """Estimate one call's footprint, or None when it can't be estimated.

    None when the model is not one EcoLogits covers or the call reports no
    output tokens. EcoLogits counts only generated (output) tokens.
    """
    mapped = ecologits_model(model_key)
    if mapped is None or completion_tokens is None or completion_tokens < 0:
        return None
    from ecologits.tracers.utils import llm_impacts

    provider, model = mapped
    impacts = llm_impacts(
        provider=provider,
        model_name=model,
        output_token_count=int(completion_tokens),
        request_latency=_UNMEASURED_LATENCY,
        electricity_mix_zone=electricity_mix_zone(str(model_key)),
    )
    if impacts.errors:
        # Settings are checked at start-up, so this is a model or zone that
        # EcoLogits stopped knowing: say so rather than record nothing quietly.
        logger.error(
            "No footprint estimate for %s (%s/%s): %s",
            model_key,
            provider,
            model,
            "; ".join(str(e) for e in impacts.errors),
        )
        return None
    return Footprint(
        energy_kwh=_as_range(impacts.energy.value),
        gwp_kgco2eq=_as_range(impacts.gwp.value),
        water_l=_as_range(impacts.wcf.value),
    )


_ROW_MEASURES = ("energy_kwh", "gwp_kgco2eq", "water_l")

# The user_activity columns these helpers fill (migration 0042).
FOOTPRINT_ROW_COLUMNS = (
    *(f"{m}_{end}" for m in _ROW_MEASURES for end in ("min", "max")),
    "footprint_unestimated_tokens",
)


def add_footprint(
    row: Any, model_key: Optional[str], completion_tokens: Optional[int]
) -> None:
    """Add one call's estimate onto an activity row, as its cost is added.

    A call EcoLogits can't estimate adds its output tokens to
    ``footprint_unestimated_tokens`` instead. A call with no output tokens
    adds nothing.
    """
    if not completion_tokens or completion_tokens < 0:
        return
    footprint = estimate_footprint(model_key, completion_tokens)
    if footprint is None:
        row.footprint_unestimated_tokens = (
            row.footprint_unestimated_tokens or 0
        ) + int(completion_tokens)
        return
    for measure, (low, high) in zip(
        _ROW_MEASURES,
        (footprint.energy_kwh, footprint.gwp_kgco2eq, footprint.water_l),
    ):
        setattr(row, f"{measure}_min", (getattr(row, f"{measure}_min") or 0.0) + low)
        setattr(row, f"{measure}_max", (getattr(row, f"{measure}_max") or 0.0) + high)


def set_footprint(
    row: Any, model_key: Optional[str], completion_tokens: Optional[int]
) -> None:
    """Replace a row's estimate with one for its totals.

    For usage the browser reports as running totals, where the cost is also
    recomputed from the totals and the row's model.
    """
    for measure in _ROW_MEASURES:
        setattr(row, f"{measure}_min", None)
        setattr(row, f"{measure}_max", None)
    row.footprint_unestimated_tokens = None
    add_footprint(row, model_key, completion_tokens)


def validate_footprint_settings() -> None:
    """Stop start-up when config.json names an EcoLogits model or zone it lacks."""
    from ecologits.electricity_mix_repository import electricity_mixes
    from ecologits.model_repository import models

    from pipeline.db import config as db_config

    problems = []
    for key, settings in (db_config.SUPPORTED_LLMS or {}).items():
        override = (settings or {}).get("ecologits")
        if override:
            provider = override.get("provider")
            model = override.get("model")
            if not provider or not model:
                problems.append(
                    f"supported_llms.{key}.ecologits needs both provider and model"
                )
            elif models.find_model(provider=provider, model_name=model) is None:
                problems.append(
                    f"supported_llms.{key}.ecologits: EcoLogits has no model "
                    f"{model!r} for provider {provider!r}"
                )
        zone = (settings or {}).get("electricity_mix_zone")
        if zone and electricity_mixes.find_electricity_mix(zone=str(zone)) is None:
            problems.append(
                f"supported_llms.{key}.electricity_mix_zone: EcoLogits has no "
                f"electricity mix for zone {zone!r}"
            )
    if problems:
        raise ValueError(
            "Footprint settings in config.json are invalid: " + "; ".join(problems)
        )
