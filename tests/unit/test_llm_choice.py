"""Tests for per-group model choices (Group Settings > LLMs): which model each
AI job uses, how choices are validated, config.json prices, and models that
refuse a temperature."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import pipeline.db as pipeline_db
from pipeline.db import config as db_config
from ui.backend.auth.schemas import AssistantChatRequest
from ui.backend.routes import assistant as assistant_routes
from ui.backend.routes import brief as brief_routes
from ui.backend.routes import summary as summary_routes
from ui.backend.routes.config import get_config_llm_defaults, get_config_llms
from ui.backend.schemas import AISummaryRequest
from ui.backend.services import citation_check_runner
from ui.backend.services import group_settings as group_settings_module
from ui.backend.services import llm_choice, test_runner
from ui.backend.utils.llm_costs import compute_cost, has_cost_data
from utils import llm_factory

LLMS = {
    "nova-2-lite": {"model": "eu.amazon.nova-2-lite-v1:0", "provider": "aws_bedrock"},
    "nova-pro": {
        "model": "eu.amazon.nova-pro-v1:0",
        "provider": "aws_bedrock",
        "price_per_million": {"input": 0.92, "output": 3.68},
    },
    "sonnet": {
        "model": "eu.anthropic.sonnet-x",
        "provider": "aws_bedrock",
        "supports_temperature": False,
    },
}
COMBO = {
    "summarization_model": {"model": "nova-2-lite", "max_tokens": 4000},
    "assistant_model": {"model": "nova-pro", "max_tokens": 2000},
    "judge_model": {"model": "sonnet"},
}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """A config.json with three models and one combo, as both the config
    module and the package see it."""
    for module in (db_config, pipeline_db):
        monkeypatch.setattr(module, "SUPPORTED_LLMS", LLMS, raising=False)
        monkeypatch.setattr(
            module, "UI_MODEL_COMBOS", {"Bedrock": COMBO}, raising=False
        )
    monkeypatch.setattr(db_config, "get_default_model_combo", lambda: "Bedrock")


def _group(name, **settings):
    return SimpleNamespace(name=name, search_settings=settings or None)


class TestValidateGroupModelChoices:
    def test_validate_when_models_listed_then_accepted(self):
        llm_choice.validate_group_model_choices(
            {"summaryModel": "nova-pro", "briefModel": "sonnet", "judgeModel": None}
        )

    def test_validate_when_no_settings_then_accepted(self):
        llm_choice.validate_group_model_choices(None)
        llm_choice.validate_group_model_choices({"rerank": True})

    def test_validate_when_model_not_listed_then_422_names_it(self):
        with pytest.raises(HTTPException) as exc:
            llm_choice.validate_group_model_choices({"judgeModel": "gpt-9"})
        assert exc.value.status_code == 422
        assert "judgeModel" in exc.value.detail and "'gpt-9'" in exc.value.detail
        assert "nova-2-lite" in exc.value.detail


class TestGroupChoice:
    def test_choice_when_several_groups_then_first_by_name_wins(self):
        groups = [
            _group("Analysts", summaryModel="nova-pro"),
            _group("Default", summaryModel="sonnet"),
        ]
        assert llm_choice.group_choice(groups, llm_choice.SUMMARY) == "nova-pro"

    def test_choice_when_first_group_leaves_it_unset_then_next_group(self):
        groups = [
            _group("Analysts", rerank=True),
            _group("Default", judgeModel="sonnet"),
        ]
        assert llm_choice.group_choice(groups, llm_choice.JUDGE) == "sonnet"

    def test_choice_when_no_group_chooses_then_none(self):
        assert llm_choice.group_choice([_group("Default")], llm_choice.BRIEF) is None

    def test_choice_when_model_left_config_then_409_names_group_and_model(self):
        with pytest.raises(HTTPException) as exc:
            llm_choice.group_choice(
                [_group("Analysts", briefModel="old-model")], llm_choice.BRIEF
            )
        assert exc.value.status_code == 409
        assert "'Analysts'" in exc.value.detail and "'old-model'" in exc.value.detail

    @pytest.mark.asyncio
    async def test_user_choice_when_no_user_then_none(self):
        assert (
            await llm_choice.user_group_choice(object(), None, llm_choice.SUMMARY)
            is None
        )

    @pytest.mark.asyncio
    async def test_user_choice_when_signed_in_then_reads_their_groups(
        self, monkeypatch
    ):
        async def fake_groups(_session, user_id):
            assert user_id == "u1"
            return [_group("Analysts", summaryModel="nova-pro")]

        monkeypatch.setattr(group_settings_module, "user_groups", fake_groups)
        user = SimpleNamespace(id="u1")
        assert (
            await llm_choice.user_group_choice(object(), user, llm_choice.SUMMARY)
            == "nova-pro"
        )


class TestConfigDefaults:
    def test_defaults_when_combo_sets_each_stage_then_each_used(self):
        assert llm_choice.config_defaults() == {
            "summary": "nova-2-lite",
            "brief": "nova-pro",
            "judge": "sonnet",
        }

    def test_defaults_when_no_assistant_or_judge_then_summary_model(self):
        combo = {"summarization_model": {"model": "nova-2-lite"}}
        assert llm_choice.combo_default(llm_choice.BRIEF, combo) == "nova-2-lite"
        assert llm_choice.combo_default(llm_choice.JUDGE, combo) == "nova-2-lite"

    def test_defaults_route_when_called_then_returns_config_models(self):
        assert get_config_llm_defaults().model_dump() == {
            "summary": "nova-2-lite",
            "brief": "nova-pro",
            "judge": "sonnet",
        }

    def test_llms_route_when_model_refuses_temperature_then_flagged(self, monkeypatch):
        import ui.backend.routes.config as config_routes

        monkeypatch.setattr(config_routes, "SUPPORTED_LLMS", LLMS)
        flags = {m.name: m.supports_temperature for m in get_config_llms()}
        assert flags == {"nova-2-lite": True, "nova-pro": True, "sonnet": False}


class TestConfigPrices:
    def test_cost_when_config_sets_price_then_config_price_used(self):
        # 1,000,000 input at $0.92 + 500,000 output at $3.68 per million.
        assert compute_cost("nova-pro", 1_000_000, 500_000) == Decimal("2.760000")
        assert has_cost_data("nova-pro")

    def test_cost_when_config_has_no_price_then_table_used(self):
        assert compute_cost("nova-2-lite", 1000, 1000) == Decimal("0.003080")

    def test_cost_when_neither_has_a_price_then_none(self):
        assert compute_cost("sonnet", 1000, 1000) is None
        assert not has_cost_data("sonnet")

    def test_load_when_price_valid_then_kept_as_floats(self):
        loaded = db_config._load_llms(
            {
                "supported_llms": {
                    "m": {
                        "model": "x",
                        "price_per_million": {"input": 1, "output": 2.5},
                    }
                }
            }
        )
        assert loaded["m"]["price_per_million"] == {"input": 1.0, "output": 2.5}

    @pytest.mark.parametrize(
        "price",
        [{"input": 1}, {"input": -1, "output": 2}, {"input": "1", "output": 2}, [1, 2]],
    )
    def test_load_when_price_malformed_then_refused(self, price):
        with pytest.raises(ValueError, match="price_per_million"):
            db_config._load_llms(
                {"supported_llms": {"m": {"model": "x", "price_per_million": price}}}
            )

    def test_load_when_temperature_flag_not_boolean_then_refused(self):
        with pytest.raises(ValueError, match="supports_temperature"):
            db_config._load_llms(
                {"supported_llms": {"m": {"model": "x", "supports_temperature": "no"}}}
            )


class TestTemperatureFlag:
    @pytest.fixture
    def created(self, monkeypatch):
        calls = []

        def fake_create(provider, model, temperature, max_tokens, inference_provider):
            calls.append({"model": model, "temperature": temperature})
            return object()

        monkeypatch.setattr(llm_factory, "_create_llm_for_provider", fake_create)
        monkeypatch.setattr(llm_factory, "_llm_cache", {}, raising=False)
        return calls

    def test_get_llm_when_model_refuses_temperature_then_none_sent(self, created):
        llm_factory.get_llm(model="sonnet", temperature=0.2, max_tokens=100)
        assert created == [{"model": "eu.anthropic.sonnet-x", "temperature": None}]

    def test_get_llm_when_model_takes_temperature_then_sent(self, created):
        llm_factory.get_llm(model="nova-pro", temperature=0.2, max_tokens=100)
        assert created == [{"model": "eu.amazon.nova-pro-v1:0", "temperature": 0.2}]


def _choice(model):
    async def fake(_session, _user, _job):
        return model

    return fake


class TestRoutesUseGroupChoice:
    @pytest.mark.asyncio
    async def test_summary_when_group_chooses_then_overrides_request(self, monkeypatch):
        monkeypatch.setattr(summary_routes, "_USER_MODULE", True)
        monkeypatch.setattr(summary_routes, "user_group_choice", _choice("nova-pro"))
        body = AISummaryRequest(
            query="q",
            results=[],
            summary_model_config={
                "model": "nova-2-lite",
                "max_tokens": 4000,
                "temperature": 0,
                "chunk_overlap": 800,
                "chunk_tokens_ratio": 0.5,
            },
        )
        assert (
            await summary_routes._summary_model_key(body, object(), object())
            == "nova-pro"
        )

    @pytest.mark.asyncio
    async def test_summary_when_no_group_choice_then_request_model(self, monkeypatch):
        monkeypatch.setattr(summary_routes, "_USER_MODULE", True)
        monkeypatch.setattr(summary_routes, "user_group_choice", _choice(None))
        body = AISummaryRequest(query="q", results=[], summary_model="nova-2-lite")
        assert (
            await summary_routes._summary_model_key(body, object(), object())
            == "nova-2-lite"
        )

    @pytest.mark.asyncio
    async def test_brief_when_group_chooses_then_overrides_request(self, monkeypatch):
        monkeypatch.setattr(brief_routes, "user_group_choice", _choice("sonnet"))
        key = await brief_routes._brief_model_key(
            "nova-2-lite", "wfp", object(), object()
        )
        assert key == "sonnet"

    @pytest.mark.asyncio
    async def test_brief_when_nothing_sent_then_configured_model(self, monkeypatch):
        monkeypatch.setattr(brief_routes, "user_group_choice", _choice(None))
        monkeypatch.setattr(
            brief_routes, "_resolve_configured_model", lambda _ds: "nova-pro"
        )
        assert (
            await brief_routes._brief_model_key(None, "wfp", None, None) == "nova-pro"
        )

    @pytest.mark.asyncio
    async def test_assistant_when_brief_request_then_group_brief_model(
        self, monkeypatch
    ):
        monkeypatch.setattr(assistant_routes, "user_group_choice", _choice("sonnet"))
        body = AssistantChatRequest(query="q", usage_context="brief")
        assert (
            await assistant_routes._purpose_model_key(
                body, "nova-2-lite", object(), object()
            )
            == "sonnet"
        )

    @pytest.mark.asyncio
    async def test_assistant_when_not_brief_then_request_model(self, monkeypatch):
        monkeypatch.setattr(assistant_routes, "user_group_choice", _choice("sonnet"))
        body = AssistantChatRequest(query="q")
        assert (
            await assistant_routes._purpose_model_key(
                body, "nova-2-lite", object(), object()
            )
            == "nova-2-lite"
        )


class TestJudgeChoice:
    def test_combo_judge_when_set_then_run_config_uses_it(self):
        cfg = test_runner.effective_config({"model_combo": "Bedrock"})
        assert cfg["summary_model"] == "nova-2-lite"
        assert cfg["judge_model"] == "sonnet"

    def test_run_as_group_when_group_chooses_models_then_they_override(self):
        out = test_runner._group_settings_to_config(
            {"summaryModel": "nova-pro", "judgeModel": "nova-2-lite"}
        )
        assert out == {"summary_model": "nova-pro", "judge_model": "nova-2-lite"}

    @pytest.mark.asyncio
    async def test_judge_when_admin_group_chooses_then_used(self, monkeypatch):
        async def fake_groups(_session, _user_id):
            return [_group("Evaluators", judgeModel="nova-pro")]

        monkeypatch.setattr(group_settings_module, "user_groups", fake_groups)
        config = {"judge_model": "sonnet"}
        assert (
            await test_runner._apply_judge_choice(object(), config, "admin-1") is None
        )
        assert config["judge_model"] == "nova-pro"

    @pytest.mark.asyncio
    async def test_judge_when_run_as_group_then_admin_choice_ignored(self, monkeypatch):
        async def fake_groups(_session, _user_id):
            raise AssertionError("the admin's groups must not be read")

        monkeypatch.setattr(group_settings_module, "user_groups", fake_groups)
        config = {"group_id": "g1", "judge_model": "sonnet"}
        assert (
            await test_runner._apply_judge_choice(object(), config, "admin-1") is None
        )
        assert config["judge_model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_judge_when_admin_choice_left_config_then_run_refused(
        self, monkeypatch
    ):
        async def fake_groups(_session, _user_id):
            return [_group("Evaluators", judgeModel="old-model")]

        monkeypatch.setattr(group_settings_module, "user_groups", fake_groups)
        problem = await test_runner._apply_judge_choice(object(), {}, "admin-1")
        assert "'Evaluators'" in problem and "'old-model'" in problem

    def test_run_when_model_unlisted_then_problem_named(self):
        problem = test_runner._unlisted_model_problem(
            {"summary_model": "nova-2-lite", "judge_model": "gpt-9"}
        )
        assert "judge model 'gpt-9'" in problem
        assert (
            test_runner._unlisted_model_problem(
                {"judge_model": "eu.amazon.nova-pro-v1:0"}
            )
            is None
        )

    def test_citation_check_judge_when_combo_sets_judge_then_used(self):
        assert citation_check_runner.resolve_judge_model("Bedrock") == "sonnet"
        assert citation_check_runner.resolve_judge_model(None) == "sonnet"
