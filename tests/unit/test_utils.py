from types import SimpleNamespace

import pipeline.db as pipeline_db
from utils import config_validator, llm_factory


def test_validate_llm_model_reference_empty_key():
    assert (
        config_validator.validate_llm_model_reference("", {"model": {}}, "path")
        is False
    )


def test_validate_llm_model_reference_missing_key():
    assert (
        config_validator.validate_llm_model_reference(
            "missing", {"present": {}}, "path"
        )
        is False
    )


def test_validate_llm_model_reference_success():
    assert (
        config_validator.validate_llm_model_reference(
            "present", {"present": {}}, "path"
        )
        is True
    )


def test_resolve_llm_model_config_with_override():
    supported = {"model_key": {"model": "M", "provider": "huggingface"}}
    resolved = config_validator.resolve_llm_model_config(
        "model_key", supported, {"temperature": 0.2}
    )
    assert resolved["model"] == "M"
    assert resolved["temperature"] == 0.2


def test_validate_all_llm_references_missing_supported():
    errors = config_validator.validate_all_llm_references({})
    assert "supported_llms" in errors[0]


def test_validate_all_llm_references_invalid_entries():
    config = {
        "supported_llms": {"good": {"model": "M"}},
        "application": {"ai_summary": {"llm": {"model": "missing"}}},
        "datasources": {
            "Source": {
                "pipeline": {
                    "summarize": {"enabled": True, "llm_model": {"model": "missing"}}
                }
            }
        },
    }
    errors = config_validator.validate_all_llm_references(config)
    assert any("missing" in error for error in errors)


def test_resolve_model_key_from_supported(monkeypatch):
    monkeypatch.setattr(
        pipeline_db,
        "SUPPORTED_LLMS",
        {
            "key": {
                "model": "Model",
                "provider": "huggingface",
                "inference_provider": "ip",
            }
        },
    )

    model, provider, inference = llm_factory._resolve_model_key("key")
    assert model == "Model"
    assert provider == "huggingface"
    assert inference == "ip"


def test_get_inference_provider_for_model(monkeypatch):
    monkeypatch.setattr(
        pipeline_db,
        "SUPPORTED_LLMS",
        {"key": {"model": "Model", "inference_provider": "ip"}},
    )

    assert llm_factory._get_inference_provider_for_model("Model", "openai") is None
    assert llm_factory._get_inference_provider_for_model("key", "huggingface") == "ip"


def test_get_llm_uses_cache(monkeypatch):
    fake_llm = SimpleNamespace(name="llm")
    calls = []

    def fake_create(model, temperature, max_tokens, inference_provider=None):
        calls.append((model, temperature, max_tokens, inference_provider))
        return fake_llm

    monkeypatch.setattr(llm_factory, "_create_huggingface_llm", fake_create)
    monkeypatch.setattr(
        pipeline_db,
        "get_application_config",
        lambda: {"llm": {"model": "key", "max_tokens": 200}},
    )
    monkeypatch.setattr(
        pipeline_db,
        "SUPPORTED_LLMS",
        {"key": {"model": "Model", "provider": "huggingface"}},
    )
    monkeypatch.setattr(llm_factory, "_llm_cache", {}, raising=False)

    llm1 = llm_factory.get_llm(temperature=0.1, max_tokens=100)
    llm2 = llm_factory.get_llm(temperature=0.1, max_tokens=100)

    assert llm1 is fake_llm
    assert llm2 is fake_llm
    assert len(calls) == 1


def test_create_huggingface_llm_when_inference_provider_set_then_router_pinned(
    monkeypatch,
):
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test")

    llm = llm_factory._create_huggingface_llm(
        "Qwen/Qwen2.5-72B-Instruct", 0.2, 100, inference_provider="together"
    )

    assert llm.llm.provider == "together"
    assert llm.llm.repo_id == "Qwen/Qwen2.5-72B-Instruct"
    assert llm.llm.temperature == 0.2
    assert llm.llm.max_new_tokens == 100


def test_create_huggingface_llm_when_no_inference_provider_then_router_chooses(
    monkeypatch,
):
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test")

    llm = llm_factory._create_huggingface_llm(
        "Qwen/Qwen2.5-72B-Instruct", 0.2, 100, inference_provider=None
    )

    assert llm.llm.provider is None


def test_get_llm_when_model_id_matches_supported_llm_then_its_provider_is_used(
    monkeypatch,
):
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test")
    monkeypatch.setattr(
        pipeline_db,
        "SUPPORTED_LLMS",
        {
            "key": {
                "model": "Org/Model",
                "provider": "huggingface",
                "inference_provider": "featherless-ai",
            }
        },
    )
    monkeypatch.setattr(llm_factory, "_llm_cache", {}, raising=False)

    llm = llm_factory.get_llm(
        model="Org/Model", provider="huggingface", temperature=0.0, max_tokens=50
    )

    assert llm.llm.provider == "featherless-ai"


# ---------------------------------------------------------------------------
# The supported_llms key a call's usage is labelled and priced by
# ---------------------------------------------------------------------------

_NOVA_ID = "us.amazon.nova-2-lite-v1:0"


def _use_llms(monkeypatch, supported_llms, default_model=None):
    """config.json's supported_llms, and its application default model."""
    from pipeline.db import config as db_config

    monkeypatch.setattr(db_config, "SUPPORTED_LLMS", supported_llms)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    llm_config = {"model": default_model} if default_model else {}
    monkeypatch.setattr(llm_factory, "_load_llm_config", lambda: llm_config)


_NOVA = {"nova-2-lite": {"model": _NOVA_ID, "provider": "aws_bedrock"}}


def test_supported_llm_key_when_key_then_key(monkeypatch):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.supported_llm_key("nova-2-lite") == "nova-2-lite"


def test_supported_llm_key_when_provider_model_id_then_its_key(monkeypatch):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.supported_llm_key(_NOVA_ID) == "nova-2-lite"


def test_supported_llm_key_when_unlisted_then_none(monkeypatch):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.supported_llm_key("mystery-llm") is None


def test_supported_llm_key_when_a_key_and_another_entrys_id_then_key_wins(
    monkeypatch,
):
    _use_llms(
        monkeypatch,
        {"alias": {"model": "gpt-4.1-mini"}, "gpt-4.1-mini": {"model": "gpt-4.1"}},
    )
    assert llm_factory.supported_llm_key("gpt-4.1-mini") == "gpt-4.1-mini"


def test_supported_llm_key_when_entries_share_an_id_then_first_wins(monkeypatch):
    _use_llms(
        monkeypatch, {"first": {"model": _NOVA_ID}, "second": {"model": _NOVA_ID}}
    )
    assert llm_factory.supported_llm_key(_NOVA_ID) == "first"


def test_resolve_effective_model_key_when_provider_id_then_its_key(monkeypatch):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.resolve_effective_model_key(_NOVA_ID) == "nova-2-lite"


def test_resolve_effective_model_key_when_unlisted_then_name_as_given(monkeypatch):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.resolve_effective_model_key("Org/Raw") == "Org/Raw"


def test_resolve_effective_model_key_when_none_and_llm_model_id_then_its_key(
    monkeypatch,
):
    _use_llms(monkeypatch, _NOVA)
    monkeypatch.setenv("LLM_MODEL", _NOVA_ID)
    assert llm_factory.resolve_effective_model_key(None) == "nova-2-lite"


def test_resolve_effective_model_key_when_none_and_config_default_then_its_key(
    monkeypatch,
):
    _use_llms(monkeypatch, _NOVA, default_model=_NOVA_ID)
    assert llm_factory.resolve_effective_model_key(None) == "nova-2-lite"


def test_resolve_effective_model_key_when_none_and_no_default_then_none(
    monkeypatch,
):
    _use_llms(monkeypatch, _NOVA)
    assert llm_factory.resolve_effective_model_key(None) is None


def test_default_model_name_when_llm_model_and_config_default_then_env_wins(
    monkeypatch,
):
    _use_llms(monkeypatch, _NOVA, default_model="gpt-4.1-mini")
    monkeypatch.setenv("LLM_MODEL", "nova-2-lite")
    assert llm_factory.default_model_name() == "nova-2-lite"
