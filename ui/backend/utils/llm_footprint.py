"""Estimated environmental footprint of one LLM call, from EcoLogits.

EcoLogits (https://ecologits.ai, MPL-2.0) estimates a text generation call's
energy use, greenhouse gas emissions and water use from the model's size and
the number of tokens it generated, for the data centre's electricity mix. It
gives each figure as a range, because model sizes, hardware and data-centre
efficiency are themselves ranges.

Each ``supported_llms`` key (the name a call's usage is recorded under, as for
its cost in ``llm_costs``) has a **basis**: the EcoLogits model(s) its calls are
estimated as, and, when those are not the model itself, the assumption that
was made. The basis is stored with each row's estimate, so the admin screen
shows where every figure came from and flags assumptions.

- **Covered:** EcoLogits knows the model itself (Haiku 4.5, GPT-4.1 mini...).
- **Alias:** Llama 3.3 70B is estimated as Llama 3.1 70B, which has the same
  architecture and exactly the same parameter count.
- **Size class:** Amazon publishes no size for Nova. SAEF's class table
  (Llopis-Garcia, Sustainable Production and Consumption 70 (2026) 320-347)
  puts Nova Lite in its small class (A) and Nova Pro in its mid class (B).
  Nova's calls get the range spanning a few of the models EcoLogits covers in
  that class (``_SMALL_CLASS``, ``_MID_CLASS``), and the assumption says which.

A model with no basis (embedding and rerank models, which EcoLogits doesn't
cover, or an unknown model) is not estimated: the caller counts its output
tokens as unestimated.

A ``supported_llms`` entry in config.json may set:

- ``ecologits``: ``{"provider": ..., "model": ..., "assumption": ...}``, the
  EcoLogits model to estimate it as, instead of this module's table. Give an
  ``assumption`` (shown on the admin screen) when that model is not the same
  model under another name;
- ``electricity_mix_zone``: where the model runs, as an EcoLogits zone code
  (ISO 3166-1 alpha-3 country such as ``IRL``, or ``WOR`` for the world).
  Without it, EcoLogits' own default for the provider applies (the USA for
  most model makers).

``validate_footprint_settings`` checks those settings at start-up, so a typo
stops the api instead of leaving every call unestimated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# (EcoLogits provider, EcoLogits model name)
EcoModel = Tuple[str, str]
# (what it is, link), shown with an assumption as its source.
Citation = Tuple[str, str]


@dataclass(frozen=True)
class Basis:
    """How one model's footprint is estimated."""

    models: Tuple[EcoModel, ...]
    # Why the estimate rests on other models' figures; None when EcoLogits
    # covers the model itself.
    assumption: Optional[str] = None
    # Where the assumption's facts come from.
    citations: Tuple[Citation, ...] = ()


_LLAMA_31_70B: EcoModel = ("huggingface_hub", "meta-llama/Meta-Llama-3.1-70B-Instruct")

# Every link below was checked to resolve on 2026-11-25.
_SAEF_CITATIONS: Tuple[Citation, ...] = (
    (
        "Llopis-Garcia, G. (2026). Accounting for purchased artificial "
        "intelligence inference in corporate greenhouse gas inventories: a "
        "token-based method. Sustainable Production and Consumption 70, 320-347",
        "https://doi.org/10.1016/j.spc.2026.11.003",
    ),
    (
        "SAEF dataset. Its table of models puts Nova Lite in the small class "
        "(A) and Nova Pro in the mid-size class (B)",
        "https://doi.org/10.5281/zenodo.20443585",
    ),
    (
        "Amazon: What is Amazon Nova? (no model sizes given)",
        "https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html",
    ),
)
_LLAMA_70B_CITATIONS: Tuple[Citation, ...] = (
    (
        "Hugging Face: Llama 3.3 70B Instruct",
        "https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct",
    ),
    (
        "Hugging Face: Llama 3.1 70B Instruct",
        "https://huggingface.co/meta-llama/Llama-3.1-70B-Instruct",
    ),
)

# Models EcoLogits covers in SAEF's classes A and B (see the module docstring).
# Not every class member: EcoLogits covers many more, and the assumptions
# below name the ones used.
_SMALL_CLASS: Tuple[EcoModel, ...] = (
    ("anthropic", "claude-haiku-4-5"),
    ("openai", "gpt-4.1-mini"),
    ("google_genai", "gemini-2.5-flash"),
    ("google_genai", "gemini-3.8-flash"),
)
_MID_CLASS: Tuple[EcoModel, ...] = (
    _LLAMA_31_70B,
    ("anthropic", "claude-sonnet-4-6"),
)

# supported_llms key -> basis. Every EcoLogits model named here is checked
# against EcoLogits' model repository by the unit tests.
FOOTPRINT_BASES: Mapping[str, Basis] = {
    # Azure Foundry (OpenAI models)
    "gpt-4.1-mini": Basis((("openai", "gpt-4.1-mini"),)),
    # Google Vertex (Gemini)
    "gemini-2.5-flash": Basis((("google_genai", "gemini-2.5-flash"),)),
    "gemini-2.5-pro": Basis((("google_genai", "gemini-2.5-pro"),)),
    "gemini-3.8-flash": Basis((("google_genai", "gemini-3.8-flash"),)),
    # Claude models, also when called through Amazon Bedrock
    "haiku-4.5": Basis((("anthropic", "claude-haiku-4-5"),)),
    "sonnet-4.6": Basis((("anthropic", "claude-sonnet-4-6"),)),
    "sonnet-5.5": Basis((("anthropic", "claude-sonnet-5-5"),)),
    # Hugging Face (open weights)
    "llama-3.1-8b-instruct": Basis(
        (("huggingface_hub", "meta-llama/Meta-Llama-3.1-8B-Instruct"),)
    ),
    # Same architecture (LlamaForCausalLM) and exactly the same parameter
    # count (70,553,706,496, Hugging Face API, 2026-11-25) as Llama 3.1 70B.
    "llama-3.3-70b-instruct": Basis(
        (_LLAMA_31_70B,),
        "EcoLogits has no figures for Llama 3.3 70B. For each call, we run "
        "EcoLogits as if Llama 3.1 70B had written the same output tokens. The "
        "two models have the same design and exactly the same number of "
        "parameters, which is mainly what EcoLogits' estimate depends on.",
        _LLAMA_70B_CITATIONS,
    ),
    # Amazon Bedrock: Amazon publishes no size for Nova.
    "nova-2-lite": Basis(
        _SMALL_CLASS,
        "Amazon doesn't publish how big Nova 2 Lite is, and EcoLogits has no "
        "figures for it, so we estimate it from similar models. SAEF, a "
        "published dataset of AI emission factors, puts Nova Lite in its "
        "small-model class, going by how Amazon describes the model. For each "
        "Nova 2 Lite call, we run EcoLogits four times, as if each of four "
        "small models it covers had written the same output tokens: Haiku 4.5, "
        "GPT-4.1 mini, Gemini 2.5 Flash and Gemini 3.8 Flash. The range shown "
        "runs from the lowest of the four results to the highest. EcoLogits "
        "covers many more small models. We chose these four.",
        _SAEF_CITATIONS,
    ),
    "nova-pro": Basis(
        _MID_CLASS,
        "Amazon doesn't publish how big Nova Pro is, and EcoLogits has no "
        "figures for it, so we estimate it from similar models. SAEF, a "
        "published dataset of AI emission factors, puts Nova Pro in its "
        "mid-size class, going by how Amazon describes the model. For each "
        "Nova Pro call, we run EcoLogits twice, as if each of two mid-size "
        "models it covers had written the same output tokens: Llama 3.1 70B "
        "and Sonnet 4.6. The range shown runs from the lower of the two "
        "results to the higher. EcoLogits covers many more mid-size models, "
        "and some, such as Gemini 2.5 Pro, have much higher estimates. We "
        "chose these two.",
        _SAEF_CITATIONS,
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


def basis_for(model_key: Optional[str]) -> Optional[Basis]:
    """How ``model_key`` is estimated: config.json's ``ecologits``, else the table."""
    if not model_key:
        return None
    override = _llm_settings(model_key).get("ecologits")
    if override:
        return Basis(
            ((str(override["provider"]), str(override["model"])),),
            override.get("assumption") or None,
        )
    return FOOTPRINT_BASES.get(model_key)


def electricity_mix_zone(model_key: str) -> Optional[str]:
    """The zone set for ``model_key`` in config.json, or None for EcoLogits' default."""
    zone = _llm_settings(model_key).get("electricity_mix_zone")
    return str(zone) if zone else None


def _as_range(value: Any) -> Range:
    """EcoLogits gives a float or a range with ``min`` and ``max``."""
    if hasattr(value, "min") and hasattr(value, "max"):
        return (float(value.min), float(value.max))
    return (float(value), float(value))


def _ecologits_estimate(
    model: EcoModel, tokens: int, zone: Optional[str], model_key: str
) -> Optional[Footprint]:
    from ecologits.tracers.utils import llm_impacts

    provider, name = model
    impacts = llm_impacts(
        provider=provider,
        model_name=name,
        output_token_count=tokens,
        request_latency=_UNMEASURED_LATENCY,
        electricity_mix_zone=zone,
    )
    if impacts.errors:
        # Settings are checked at start-up, so this is a model or zone that
        # EcoLogits stopped knowing: say so rather than record nothing quietly.
        logger.error(
            "No footprint estimate for %s (%s/%s): %s",
            model_key,
            provider,
            name,
            "; ".join(str(e) for e in impacts.errors),
        )
        return None
    return Footprint(
        energy_kwh=_as_range(impacts.energy.value),
        gwp_kgco2eq=_as_range(impacts.gwp.value),
        water_l=_as_range(impacts.wcf.value),
    )


def _span(ranges: List[Range]) -> Range:
    """The range covering all of ``ranges``."""
    return (min(low for low, _ in ranges), max(high for _, high in ranges))


def estimate_footprint(
    model_key: Optional[str], completion_tokens: Optional[int]
) -> Optional[Footprint]:
    """Estimate one call's footprint, or None when it can't be estimated.

    None when the model has no basis or the call reports no output tokens.
    EcoLogits counts only generated (output) tokens. A basis of several models
    gives the range spanning all of their ranges.
    """
    basis = basis_for(model_key)
    if basis is None or completion_tokens is None or completion_tokens < 0:
        return None
    zone = electricity_mix_zone(str(model_key))
    estimates = []
    for model in basis.models:
        estimate = _ecologits_estimate(
            model, int(completion_tokens), zone, str(model_key)
        )
        if estimate is None:
            return None
        estimates.append(estimate)
    return Footprint(
        energy_kwh=_span([e.energy_kwh for e in estimates]),
        gwp_kgco2eq=_span([e.gwp_kgco2eq for e in estimates]),
        water_l=_span([e.water_l for e in estimates]),
    )


def describe_basis(model_key: str) -> Dict[str, Any]:
    """How ``model_key``'s figures were estimated, for the admin screen."""
    basis = basis_for(model_key)
    if basis is None:
        return {
            "model": model_key,
            "ecologits_models": [],
            "assumed": True,
            "assumption": "Estimated with a setting that is no longer configured.",
        }
    return {
        "model": model_key,
        "ecologits_models": [f"{p}/{m}" for p, m in basis.models],
        "assumed": basis.assumption is not None,
        "assumption": basis.assumption,
    }


def _range_dict(value: Any) -> Dict[str, float]:
    low, high = _as_range(value)
    return {"min": low, "max": high}


def _parameters(architecture: Any) -> Tuple[Dict[str, float], Dict[str, float]]:
    """(active, total) parameters in billions; the same for a dense model."""
    parameters = architecture.parameters
    if hasattr(parameters, "active"):
        return _range_dict(parameters.active), _range_dict(parameters.total)
    return _range_dict(parameters), _range_dict(parameters)


# The example call the admin screen's pop-up works the calculation through.
# Estimates grow almost, not exactly, in proportion to output tokens, so the
# pop-up shows one call of this size rather than a rate per token.
EXAMPLE_OUTPUT_TOKENS = 1000


def _footprint_dict(footprint: Footprint) -> Dict[str, Dict[str, float]]:
    return {
        measure: {"min": low, "max": high}
        for measure, (low, high) in (
            ("energy_kwh", footprint.energy_kwh),
            ("gwp_kgco2eq", footprint.gwp_kgco2eq),
            ("water_l", footprint.water_l),
        )
    }


def _describe_ecologits_model(
    model: EcoModel, zone: Optional[str], model_key: str
) -> Dict[str, Any]:
    """The figures EcoLogits used for ``model``, for the admin screen.

    Its size and whether that size is published, the data-centre settings
    EcoLogits assumes for the provider, the electricity mix of the zone the
    estimate used (config.json's zone, else the provider's default), and its
    estimate for the example call.
    """
    from ecologits.electricity_mix_repository import electricity_mixes
    from ecologits.model_repository import models
    from ecologits.tracers.utils import PROVIDER_CONFIG_MAP

    provider, name = model
    found = models.find_model(provider=provider, model_name=name)
    if found is None:
        raise ValueError(f"EcoLogits has no model {name!r} for provider {provider!r}")
    datacenter = PROVIDER_CONFIG_MAP[provider]
    used_zone = zone or datacenter.datacenter_location or "WOR"
    mix = electricity_mixes.find_electricity_mix(zone=used_zone)
    if mix is None:
        raise ValueError(f"EcoLogits has no electricity mix for zone {used_zone!r}")
    active, total = _parameters(found.architecture)
    example = _ecologits_estimate(model, EXAMPLE_OUTPUT_TOKENS, zone, model_key)
    if example is None:
        raise ValueError(f"EcoLogits gave no estimate for {provider}/{name}")
    return {
        "provider": provider,
        "model": name,
        "architecture": found.architecture.type.value,
        "active_parameters_billion": active,
        "total_parameters_billion": total,
        # EcoLogits flags models whose architecture was never published: their
        # size is EcoLogits' own estimate.
        "size_published": not any(
            w.code == "model-arch-not-released" for w in found.warnings
        ),
        # A Hugging Face model's name is its page on the Hub.
        "model_card": (
            f"https://huggingface.co/{name}" if provider == "huggingface_hub" else None
        ),
        "pue": _range_dict(datacenter.datacenter_pue),
        "onsite_water_l_per_kwh": _range_dict(datacenter.datacenter_wue),
        "zone": used_zone,
        "zone_from_config": zone is not None,
        "grid_gwp_kgco2eq_per_kwh": mix.gwp,
        "grid_water_l_per_kwh": mix.wue,
        "example_estimate": _footprint_dict(example),
    }


def describe_sources(model_key: str) -> Dict[str, Any]:
    """Everything behind ``model_key``'s figures, for the admin screen's pop-up.

    The assumption and its citations; for each EcoLogits model the estimate
    rests on, the figures EcoLogits used and its estimate for an example call
    of ``EXAMPLE_OUTPUT_TOKENS`` output tokens; and the estimate recorded for
    that call, which spans the models' estimates.
    """
    basis = basis_for(model_key)
    if basis is None:
        return {
            **describe_basis(model_key),
            "citations": [],
            "models": [],
            "example_output_tokens": EXAMPLE_OUTPUT_TOKENS,
            "example_estimate": None,
        }
    zone = electricity_mix_zone(model_key)
    example = estimate_footprint(model_key, EXAMPLE_OUTPUT_TOKENS)
    if example is None:
        raise ValueError(f"No footprint estimate for {model_key}")
    return {
        **describe_basis(model_key),
        "citations": [{"label": label, "url": url} for label, url in basis.citations],
        "models": [_describe_ecologits_model(m, zone, model_key) for m in basis.models],
        "example_output_tokens": EXAMPLE_OUTPUT_TOKENS,
        "example_estimate": _footprint_dict(example),
    }


def footprint_method() -> Dict[str, str]:
    """The tool and version the estimates come from."""
    return {"name": "EcoLogits", "version": version("ecologits")}


_ROW_MEASURES = ("energy_kwh", "gwp_kgco2eq", "water_l")

# The user_activity columns these helpers fill (migration 0042).
# ``footprint_basis`` maps each estimated model to its output tokens.
FOOTPRINT_ROW_COLUMNS = (
    *(f"{m}_{end}" for m in _ROW_MEASURES for end in ("min", "max")),
    "footprint_unestimated_tokens",
    "footprint_basis",
)


def add_footprint(
    row: Any, model_key: Optional[str], completion_tokens: Optional[int]
) -> None:
    """Add one call's estimate onto an activity row, as its cost is added.

    The call's output tokens are added to ``footprint_basis`` under its model,
    so the row records what its figures rest on. A call that can't be
    estimated adds its output tokens to ``footprint_unestimated_tokens``
    instead. A call with no output tokens adds nothing.
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
    # A new dict, so the ORM sees the JSONB change.
    basis = dict(row.footprint_basis or {})
    basis[str(model_key)] = basis.get(str(model_key), 0) + int(completion_tokens)
    row.footprint_basis = basis


def set_footprint(
    row: Any, model_key: Optional[str], completion_tokens: Optional[int]
) -> None:
    """Replace a row's estimate with one for its totals.

    For usage the browser reports as running totals, where the cost is also
    recomputed from the totals and the row's model.
    """
    for column in FOOTPRINT_ROW_COLUMNS:
        setattr(row, column, None)
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
