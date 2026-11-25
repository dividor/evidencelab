"""Tests for the per-model LLM cost table and ``compute_cost`` helper."""

from decimal import Decimal

import pytest

from ui.backend.utils.llm_costs import LLM_COSTS_PER_1K, compute_cost, has_cost_data


@pytest.mark.unit
class TestComputeCostKnownModel:
    """Cost computation for models present in the rate table."""

    def test_basic_gpt_4_1_mini(self):
        """Sum of (in * input_rate + out * output_rate) / 1k, quantised to 6dp."""
        # 1000 input @ $0.00040/1k = $0.00040
        # 500 output @ $0.00160/1k = $0.00080
        # total = $0.00120
        assert compute_cost("gpt-4.1-mini", 1000, 500) == Decimal("0.001200")

    def test_haiku_4_5_when_priced_then_uses_eu_bedrock_rates(self):
        """Anthropic's Haiku 4.5 is priced at Bedrock's EU profile rates."""
        # 8500 input @ $0.00110/1k = $0.009350
        # 613 output @ $0.00550/1k = $0.0033715
        # total = $0.0127215, quantised to $0.012722
        assert compute_cost("haiku-4.5", 8500, 613) == Decimal("0.012722")
        assert has_cost_data("haiku-4.5")

    def test_input_only(self):
        """An LLM that produced 0 output tokens still incurs input cost."""
        assert compute_cost("gpt-4.1-mini", 1000, 0) == Decimal("0.000400")

    def test_output_only(self):
        """And vice versa — an output-only call is computable."""
        assert compute_cost("gpt-4.1-mini", 0, 1000) == Decimal("0.001600")

    def test_quantises_to_micro_dollars(self):
        """Result is always rounded to 6 decimal places."""
        cost = compute_cost("gemini-2.5-pro", 1, 1)
        assert cost is not None
        # Decimal exponent should be -6 (i.e. quantised to 0.000001).
        assert cost.as_tuple().exponent == -6

    def test_large_token_counts(self):
        """A 1M-token call still computes without overflow."""
        cost = compute_cost("gpt-4.1-mini", 1_000_000, 1_000_000)
        # 1M @ $0.00040/1k = $0.40 input; 1M @ $0.00160/1k = $1.60 output
        assert cost == Decimal("2.000000")


@pytest.mark.unit
class TestComputeCostMissingInputs:
    """Edge cases where the helper must return ``None``."""

    def test_unknown_model_returns_none(self):
        """A model not in the table returns None so the UI shows '—'."""
        assert compute_cost("not-a-real-model", 100, 50) is None

    def test_no_model_returns_none(self):
        """Empty model_key returns None — never fabricate a cost."""
        assert compute_cost(None, 100, 50) is None
        assert compute_cost("", 100, 50) is None

    def test_both_token_counts_none_returns_none(self):
        """When the provider reported no usage at all, return None."""
        assert compute_cost("gpt-4.1-mini", None, None) is None

    def test_one_token_count_provided(self):
        """One side provided is enough — missing side is treated as zero."""
        # 1k input @ $0.00040 = $0.00040, no output cost.
        assert compute_cost("gpt-4.1-mini", 1000, None) == Decimal("0.000400")

    def test_negative_token_counts_treated_as_zero(self):
        """Malformed negative counts should not produce a negative cost."""
        assert compute_cost("gpt-4.1-mini", -50, -50) == Decimal("0")


@pytest.mark.unit
class TestHasCostData:
    """has_cost_data flag."""

    def test_known_model(self):
        assert has_cost_data("gpt-4.1-mini") is True

    def test_unknown_model(self):
        assert has_cost_data("not-a-real-model") is False

    def test_empty_key(self):
        assert has_cost_data(None) is False
        assert has_cost_data("") is False


@pytest.mark.unit
def test_cost_table_is_well_formed():
    """Every entry is a (Decimal, Decimal) tuple with non-negative rates.

    Guards against typos (string entries, dropped values) the moment a
    new model is added.
    """
    assert LLM_COSTS_PER_1K, "Cost table must not be empty"
    for key, value in LLM_COSTS_PER_1K.items():
        assert isinstance(key, str) and key, f"Invalid key: {key!r}"
        assert (
            isinstance(value, tuple) and len(value) == 2
        ), f"Entry for {key!r} must be a (input, output) tuple"
        input_rate, output_rate = value
        assert isinstance(input_rate, Decimal), f"{key} input rate must be Decimal"
        assert isinstance(output_rate, Decimal), f"{key} output rate must be Decimal"
        assert input_rate >= 0 and output_rate >= 0, f"{key} rates must be non-negative"
