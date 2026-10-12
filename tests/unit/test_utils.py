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
