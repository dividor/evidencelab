"""Per-model LLM cost table and cost computation.

The cost table maps a model identifier (the ``supported_llms`` key from
``config.json``, e.g. ``gpt-4.1-mini``) to public list prices in USD per
1,000 tokens, split by input and output.

Adding a new model is a one-line change here. Unlisted models cause
``compute_cost`` to return ``None`` so the admin UI renders an em-dash
rather than fabricating a cost value.

Prices reflect public list pricing as of 2026-05 and may drift; treat
them as best-effort. The DB stores the computed cost as ``NUMERIC(12, 6)``
so per-call USD figures are stored with micro-dollar precision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Optional

# (input_per_1k_tokens, output_per_1k_tokens) in USD.
# Keys match ``supported_llms`` keys in config.json.
LLM_COSTS_PER_1K: Mapping[str, tuple[Decimal, Decimal]] = {
    # Azure Foundry (OpenAI-family deployments)
    "gpt-4.1-mini": (Decimal("0.00040"), Decimal("0.00160")),
    # Google Vertex (Gemini family)
    "gemini-2.0-flash": (Decimal("0.00010"), Decimal("0.00040")),
    "gemini-2.5-flash": (Decimal("0.00030"), Decimal("0.00250")),
    "gemini-2.5-pro": (Decimal("0.00125"), Decimal("0.01000")),
    # Introductory price through 2026-12-31; $1.50 / $7.50 per 1M from 2027.
    "gemini-3.8-flash": (Decimal("0.00075"), Decimal("0.00375")),
    # Amazon Bedrock (us-east-2, from the AWS Price List API, 2026-11)
    "nova-2-lite": (Decimal("0.00033"), Decimal("0.00275")),
    # HuggingFace-hosted open-weights — provider-dependent; left None
    # below by omitting an entry so the UI shows "—" for these models.
}


def compute_cost(
    model_key: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
) -> Optional[Decimal]:
    """Return USD cost for the call, or ``None`` if it can't be computed.

    Returns ``None`` when ``model_key`` is unknown, when both token
    counts are missing, or when either rate is not configured. Negative
    token counts are treated as zero to avoid producing negative costs
    from malformed upstream usage payloads.
    """
    if not model_key:
        return None
    rates = LLM_COSTS_PER_1K.get(model_key)
    if rates is None:
        return None
    if prompt_tokens is None and completion_tokens is None:
        return None
    input_rate, output_rate = rates
    p = max(prompt_tokens or 0, 0)
    c = max(completion_tokens or 0, 0)
    cost = (Decimal(p) * input_rate + Decimal(c) * output_rate) / Decimal(1000)
    return cost.quantize(Decimal("0.000001"))


def has_cost_data(model_key: Optional[str]) -> bool:
    """Return True if a cost lookup exists for ``model_key``."""
    return bool(model_key) and model_key in LLM_COSTS_PER_1K
