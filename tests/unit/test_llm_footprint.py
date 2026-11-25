"""Estimated footprint of LLM calls (ui/backend/utils/llm_footprint.py).

Uses the real EcoLogits package, so the model table is checked against its
model repository and the estimates against its own figures.
"""

import logging
from importlib.metadata import version
from types import SimpleNamespace

import pytest
from ecologits.electricity_mix_repository import electricity_mixes
from ecologits.model_repository import models as ecologits_models

from pipeline.db import config as db_config
from ui.backend.utils import llm_footprint
from ui.backend.utils.llm_footprint import (
    FOOTPRINT_BASES,
    FOOTPRINT_ROW_COLUMNS,
    Basis,
    add_footprint,
    describe_basis,
    describe_sources,
    estimate_footprint,
    footprint_method,
    set_footprint,
    validate_footprint_settings,
)

# A chat model EcoLogits doesn't cover and the table has no basis for.
UNCOVERED = "gemini-2.0-flash"


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
    @pytest.mark.parametrize("key,basis", sorted(FOOTPRINT_BASES.items()))
    def test_every_basis_model_is_in_ecologits(self, key, basis):
        for provider, model in basis.models:
            assert ecologits_models.find_model(provider=provider, model_name=model), key

    @pytest.mark.parametrize(
        "key", ["nova-2-lite", "nova-pro", "llama-3.3-70b-instruct"]
    )
    def test_estimates_resting_on_other_models_say_so(self, key):
        assert FOOTPRINT_BASES[key].assumption

    @pytest.mark.parametrize("key", ["haiku-4.5", "gpt-4.1-mini", "gemini-2.5-flash"])
    def test_models_ecologits_covers_carry_no_assumption(self, key):
        assert FOOTPRINT_BASES[key].assumption is None


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

    @pytest.mark.parametrize("key", [UNCOVERED, "unknown", None, ""])
    def test_models_with_no_basis_are_not_estimated(self, llms, key):
        assert estimate_footprint(key, 500) is None

    @pytest.mark.parametrize(
        "key,members",
        [
            (
                "nova-2-lite",
                ["haiku-4.5", "gpt-4.1-mini", "gemini-2.5-flash", "gemini-3.8-flash"],
            ),
            ("nova-pro", ["llama-3.3-70b-instruct", "sonnet-4.6"]),
        ],
    )
    def test_nova_spans_the_models_of_its_size_class(self, llms, key, members):
        # Amazon publishes no size for Nova, so its range covers its class.
        nova = estimate_footprint(key, 1000)
        estimates = [estimate_footprint(m, 1000) for m in members]
        for measure in ("energy_kwh", "gwp_kgco2eq", "water_l"):
            low, high = getattr(nova, measure)
            assert low == min(getattr(e, measure)[0] for e in estimates)
            assert high == max(getattr(e, measure)[1] for e in estimates)

    def test_nova_uses_its_own_zone_for_every_class_model(self, llms):
        llms({"nova-2-lite": {"electricity_mix_zone": "SWE"}})
        sweden = estimate_footprint("nova-2-lite", 1000)
        llms({"nova-2-lite": {"electricity_mix_zone": "USA"}})
        usa = estimate_footprint("nova-2-lite", 1000)
        assert sweden.energy_kwh == usa.energy_kwh
        assert sweden.gwp_kgco2eq[1] < usa.gwp_kgco2eq[1]

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
        assert describe_basis("my-gpt")["assumed"] is False

    def test_config_mapping_can_state_its_assumption(self, llms):
        llms(
            {
                "my-model": {
                    "ecologits": {
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                        "assumption": "Assumed to be like GPT-4.1 mini.",
                    }
                }
            }
        )
        assert describe_basis("my-model") == {
            "model": "my-model",
            "ecologits_models": ["openai/gpt-4.1-mini"],
            "assumed": True,
            "assumption": "Assumed to be like GPT-4.1 mini.",
        }

    def test_a_model_ecologits_no_longer_knows_is_logged_not_estimated(
        self, llms, monkeypatch, caplog
    ):
        monkeypatch.setattr(
            llm_footprint,
            "FOOTPRINT_BASES",
            {"gone": Basis((("openai", "no-such-model"),))},
        )
        with caplog.at_level(logging.ERROR, logger=llm_footprint.__name__):
            assert estimate_footprint("gone", 500) is None
        assert "No footprint estimate for gone" in caplog.text


class TestDescribeSources:
    """What the admin screen's Basis pop-up shows for each model."""

    @pytest.mark.parametrize(
        "key", sorted(k for k, b in FOOTPRINT_BASES.items() if b.assumption)
    )
    def test_every_assumption_cites_its_sources(self, llms, key):
        citations = describe_sources(key)["citations"]
        assert citations
        for citation in citations:
            assert citation["label"]
            assert citation["url"].startswith("https://")

    def test_nova_lists_each_class_model_it_spans(self, llms):
        source = describe_sources("nova-2-lite")
        assert source["assumed"] is True
        assert [f"{m['provider']}/{m['model']}" for m in source["models"]] == (
            source["ecologits_models"]
        )
        assert len(source["models"]) == len(FOOTPRINT_BASES["nova-2-lite"].models)

    def test_closed_model_size_is_flagged_as_ecologits_estimate(self, llms):
        (haiku,) = describe_sources("haiku-4.5")["models"]
        assert haiku["size_published"] is False
        assert haiku["model_card"] is None
        found = ecologits_models.find_model(
            provider="anthropic", model_name="claude-haiku-4-5"
        )
        assert haiku["active_parameters_billion"] == {
            "min": float(found.architecture.parameters.min),
            "max": float(found.architecture.parameters.max),
        }

    def test_open_model_size_is_published_with_its_model_card(self, llms):
        (llama,) = describe_sources("llama-3.3-70b-instruct")["models"]
        assert llama["size_published"] is True
        assert llama["architecture"] == "dense"
        assert llama["active_parameters_billion"] == llama["total_parameters_billion"]
        assert llama["model_card"] == (
            "https://huggingface.co/meta-llama/Meta-Llama-3.1-70B-Instruct"
        )

    def test_mixture_of_experts_gives_active_and_total_parameters(self, llms):
        (sonnet,) = describe_sources("sonnet-4.6")["models"]
        assert sonnet["architecture"] == "moe"
        assert (
            sonnet["active_parameters_billion"]["max"]
            < sonnet["total_parameters_billion"]["min"]
        )

    def test_zone_is_the_providers_default_without_config(self, llms):
        (haiku,) = describe_sources("haiku-4.5")["models"]
        usa = electricity_mixes.find_electricity_mix(zone="USA")
        assert haiku["zone"] == "USA"
        assert haiku["zone_from_config"] is False
        assert haiku["grid_gwp_kgco2eq_per_kwh"] == usa.gwp
        assert haiku["grid_water_l_per_kwh"] == usa.wue

    def test_zone_from_config_applies_to_every_class_model(self, llms):
        llms({"nova-pro": {"electricity_mix_zone": "IRL"}})
        irl = electricity_mixes.find_electricity_mix(zone="IRL")
        for model in describe_sources("nova-pro")["models"]:
            assert model["zone"] == "IRL"
            assert model["zone_from_config"] is True
            assert model["grid_gwp_kgco2eq_per_kwh"] == irl.gwp

    def test_model_with_no_basis_has_no_sources(self, llms):
        source = describe_sources(UNCOVERED)
        assert source["models"] == []
        assert source["citations"] == []
        assert source["assumed"] is True

    def test_method_names_the_installed_ecologits(self):
        assert footprint_method() == {
            "name": "EcoLogits",
            "version": version("ecologits"),
        }


class TestRowHelpers:
    def test_add_footprint_adds_up_calls(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 400)
        once = (row.energy_kwh_min, row.energy_kwh_max)
        add_footprint(row, "haiku-4.5", 400)
        assert row.energy_kwh_min == pytest.approx(2 * once[0])
        assert row.energy_kwh_max == pytest.approx(2 * once[1])
        assert row.footprint_unestimated_tokens is None
        assert row.footprint_basis == {"haiku-4.5": 800}

    def test_add_footprint_records_each_models_tokens_in_the_basis(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 400)
        add_footprint(row, "nova-2-lite", 300)
        add_footprint(row, "nova-2-lite", 200)
        assert row.footprint_basis == {"haiku-4.5": 400, "nova-2-lite": 500}
        assert row.footprint_unestimated_tokens is None

    def test_add_footprint_counts_tokens_it_cannot_estimate(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 400)
        add_footprint(row, UNCOVERED, 300)
        add_footprint(row, UNCOVERED, 200)
        assert row.energy_kwh_min > 0
        assert row.footprint_unestimated_tokens == 500
        assert row.footprint_basis == {"haiku-4.5": 400}

    @pytest.mark.parametrize("tokens", [0, None, -5])
    def test_add_footprint_ignores_calls_with_no_output(self, llms, tokens):
        row = _row()
        add_footprint(row, "haiku-4.5", tokens)
        assert all(getattr(row, c) is None for c in FOOTPRINT_ROW_COLUMNS)

    def test_set_footprint_replaces_what_was_there(self, llms):
        row = _row()
        add_footprint(row, "haiku-4.5", 5000)
        add_footprint(row, UNCOVERED, 100)
        set_footprint(row, "haiku-4.5", 400)
        expected = estimate_footprint("haiku-4.5", 400)
        assert (row.energy_kwh_min, row.energy_kwh_max) == expected.energy_kwh
        assert (row.water_l_min, row.water_l_max) == expected.water_l
        assert row.footprint_unestimated_tokens is None
        assert row.footprint_basis == {"haiku-4.5": 400}


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
