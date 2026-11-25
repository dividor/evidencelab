"""Estimated footprint of LLM calls (ui/backend/utils/llm_footprint.py).

Uses the real EcoLogits package, so the model table is checked against its
model repository and the estimates against its own figures.
"""

import logging
from types import SimpleNamespace

import pytest
from ecologits.model_repository import models as ecologits_models

from pipeline.db import config as db_config
from ui.backend.utils import llm_footprint
from ui.backend.utils.llm_footprint import (
    ECOLOGITS_MODELS,
    FOOTPRINT_ROW_COLUMNS,
    add_footprint,
    estimate_footprint,
    set_footprint,
    validate_footprint_settings,
)


@pytest.fixture
def llms(monkeypatch):
    """Replace config.json's supported_llms for one test."""

    def _set(entries):
        monkeypatch.setattr(db_config, "SUPPORTED_LLMS", entries)

    _set({})
    return _set


def _row():
    return SimpleNamespace(**{c: None for c in FOOTPRINT_ROW_COLUMNS})


class TestModelTable:
    @pytest.mark.parametrize("key,mapping", sorted(ECOLOGITS_MODELS.items()))
    def test_every_mapped_model_is_in_ecologits(self, key, mapping):
        provider, model = mapping
        assert ecologits_models.find_model(provider=provider, model_name=model), key


class TestEstimateFootprint:
    def test_covered_model_gives_positive_ranges(self, llms):
        footprint = estimate_footprint("haiku-4.5", 800)
        for low, high in (
            footprint.energy_kwh,
            footprint.gwp_kgco2eq,
            footprint.water_l,
        ):
            assert 0 < low <= high

    def test_more_output_tokens_means_more_energy(self, llms):
        short = estimate_footprint("gpt-4.1-mini", 100)
        long = estimate_footprint("gpt-4.1-mini", 2000)
        assert long.energy_kwh[0] > short.energy_kwh[0]
        assert long.energy_kwh[1] > short.energy_kwh[1]

    @pytest.mark.parametrize("key", ["nova-2-lite", "nova-pro", "unknown", None, ""])
    def test_models_ecologits_does_not_cover_are_not_estimated(self, llms, key):
        assert estimate_footprint(key, 500) is None

    def test_no_output_token_count_is_not_estimated(self, llms):
        assert estimate_footprint("haiku-4.5", None) is None

    def test_zone_from_config_changes_the_emissions_not_the_energy(self, llms):
        llms({"haiku-4.5": {"electricity_mix_zone": "SWE"}})
        sweden = estimate_footprint("haiku-4.5", 800)
        llms({"haiku-4.5": {"electricity_mix_zone": "USA"}})
        usa = estimate_footprint("haiku-4.5", 800)
        # Same model and tokens, so the same energy; Sweden's grid emits far less.
        assert sweden.energy_kwh == usa.energy_kwh
        assert sweden.gwp_kgco2eq[1] < usa.gwp_kgco2eq[0]

    def test_config_can_map_a_model_the_table_lacks(self, llms):
        llms({"my-gpt": {"ecologits": {"provider": "openai", "model": "gpt-4.1-mini"}}})
        assert estimate_footprint("my-gpt", 500) == estimate_footprint(
            "gpt-4.1-mini", 500
        )

    def test_a_model_ecologits_no_longer_knows_is_logged_not_estimated(
        self, llms, monkeypatch, caplog
    ):
        monkeypatch.setattr(
            llm_footprint, "ECOLOGITS_MODELS", {"gone": ("openai", "no-such-model")}
        )
        with caplog.at_level(logging.ERROR, logger=llm_footprint.__name__):
            assert estimate_footprint("gone", 500) is None
        assert "No footprint estimate for gone" in caplog.text


class TestRowHelpers:
    def test_add_footprint_adds_up_calls(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 400)
        once = (row.energy_kwh_min, row.energy_kwh_max)
        add_footprint(row, "haiku-4.5", 400)
        assert row.energy_kwh_min == pytest.approx(2 * once[0])
        assert row.energy_kwh_max == pytest.approx(2 * once[1])
        assert row.footprint_unestimated_tokens is None

    def test_add_footprint_counts_tokens_it_cannot_estimate(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 400)
        add_footprint(row, "nova-2-lite", 300)
        add_footprint(row, "nova-2-lite", 200)
        assert row.energy_kwh_min > 0
        assert row.footprint_unestimated_tokens == 500

    @pytest.mark.parametrize("tokens", [0, None, -5])
    def test_add_footprint_ignores_calls_with_no_output(self, llms, tokens):
        row = _row()
        add_footprint(row, "haiku-4.5", tokens)
        assert all(getattr(row, c) is None for c in FOOTPRINT_ROW_COLUMNS)

    def test_set_footprint_replaces_what_was_there(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 5000)
        add_footprint(row, "nova-2-lite", 100)
        set_footprint(row, "haiku-4.5", 400)
        expected = estimate_footprint("haiku-4.5", 400)
        assert (row.energy_kwh_min, row.energy_kwh_max) == expected.energy_kwh
        assert (row.water_l_min, row.water_l_max) == expected.water_l
        assert row.footprint_unestimated_tokens is None


class TestValidateSettings:
    def test_valid_settings_pass(self, llms):
        llms(
            {
                "haiku-4.5": {"electricity_mix_zone": "IRL"},
                "my-gpt": {
                    "ecologits": {"provider": "openai", "model": "gpt-4.1-mini"}
                },
                "nova-2-lite": {},
            }
        )
        validate_footprint_settings()

    def test_unknown_zone_stops_start_up(self, llms):
        llms({"haiku-4.5": {"electricity_mix_zone": "XYZ"}})
        with pytest.raises(ValueError, match="no electricity mix for zone 'XYZ'"):
            validate_footprint_settings()

    def test_unknown_ecologits_model_stops_start_up(self, llms):
        llms({"x": {"ecologits": {"provider": "openai", "model": "gpt-99"}}})
        with pytest.raises(ValueError, match="has no model 'gpt-99'"):
            validate_footprint_settings()

    def test_incomplete_ecologits_setting_stops_start_up(self, llms):
        llms({"x": {"ecologits": {"model": "gpt-4.1-mini"}}})
        with pytest.raises(ValueError, match="needs both provider and model"):
            validate_footprint_settings()
