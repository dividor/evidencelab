"""EmbeddingService routing for the OpenAI-compatible source."""

import pytest

from pipeline.db import config as db_config
from pipeline.utilities import embedding_service as mod
from pipeline.utilities.openai_embedding_client import OpenAIEmbeddingClient


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setitem(
        mod.DB_VECTORS,
        "oa",
        {"model_id": "embed-x", "source": "openai", "size": 8, "type": "dense"},
    )
    monkeypatch.setitem(
        mod.DB_VECTORS,
        "oa_custom",
        {
            "model_id": "embed-y",
            "source": "openai",
            "base_url_env": "OTHER_URL",
            # pragma: allowlist nextline secret
            "api_key_env": "OTHER_KEY",
        },
    )
    return mod.EmbeddingService(embedding_api_url="http://unused")


def test_default_env_names(service, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    client = service.get_model("oa")
    assert isinstance(client, OpenAIEmbeddingClient)
    assert client.base_url == "https://api.example.com/v1"
    assert client.model_name == "embed-x"
    assert client.api_key == "k"


def test_custom_env_names(service, monkeypatch):
    monkeypatch.setenv("OTHER_URL", "https://other.example.com")
    monkeypatch.setenv("OTHER_KEY", "k2")
    client = service.get_model("oa_custom")
    assert client.base_url == "https://other.example.com"
    # pragma: allowlist nextline secret
    assert client.api_key == "k2"


def test_missing_base_url_raises(service, monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        service.get_model("oa")


def test_client_is_cached(service, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    assert service.get_model("oa") is service.get_model("oa")


# The name of the second service's key variable (a name, not a key).
SECOND_SERVICE_VARIABLE = "SECOND_EMBED_KEY"


class TestOptionsFromConfigJson:
    """The model's options must survive the registry built from config.json."""

    @staticmethod
    def _register(monkeypatch, **options):
        config = {
            "supported_embedding_models": {
                "second": {
                    "model_id": "embed-z",
                    "size": 8,
                    "source": "openai",
                    "type": "dense",
                    **options,
                }
            }
        }
        entry = db_config._load_embedding_models(config)["second"]
        monkeypatch.setitem(mod.DB_VECTORS, "second", entry)
        return entry

    def test_load_when_options_set_then_client_uses_them(self, monkeypatch):
        second_service = "value-of-the-second-variable"
        monkeypatch.setenv("SECOND_EMBED_URL", "https://second.example.com/v1")
        monkeypatch.setenv(SECOND_SERVICE_VARIABLE, second_service)
        self._register(
            monkeypatch,
            base_url_env="SECOND_EMBED_URL",
            api_key_env=SECOND_SERVICE_VARIABLE,
        )
        client = mod.EmbeddingService(embedding_api_url="http://unused").get_model(
            "second"
        )
        assert client.base_url == "https://second.example.com/v1"
        assert client.api_key == second_service

    def test_load_when_options_absent_then_defaults_apply(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
        entry = self._register(monkeypatch)
        assert "base_url_env" not in entry
        assert "api_key_env" not in entry
        client = mod.EmbeddingService(embedding_api_url="http://unused").get_model(
            "second"
        )
        assert client.base_url == "https://api.example.com/v1"
