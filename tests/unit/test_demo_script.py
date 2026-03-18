"""
test_demo_script.py - Unit tests for scripts/demo/run_demo.py
"""

from unittest import mock

import pytest

# Import the demo module
import scripts.demo.run_demo as demo


# ---------------------------------------------------------------------------
# _mask
# ---------------------------------------------------------------------------
class TestMask:
    def test_short_value(self):
        assert demo._mask("abc") == "****"

    def test_exact_four(self):
        assert demo._mask("abcd") == "****"

    def test_longer_value(self):
        assert demo._mask("my-secret-key") == "*********-key"

    def test_empty(self):
        assert demo._mask("") == "****"


# ---------------------------------------------------------------------------
# write_env_file
# ---------------------------------------------------------------------------
class TestWriteEnvFile:
    def test_creates_from_example_when_no_env(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text("FOO=\nBAR=old\n# comment\nBAZ=keep\n", encoding="utf-8")
        env_path = tmp_path / ".env"

        with mock.patch.object(demo, "ENV_PATH", env_path), mock.patch.object(
            demo, "ENV_EXAMPLE", example
        ):
            demo.write_env_file({"FOO": "new_foo", "BAR": "new_bar"})

        content = env_path.read_text()
        assert "FOO=new_foo" in content
        assert "BAR=new_bar" in content
        assert "BAZ=keep" in content
        assert "# comment" in content

    def test_updates_existing_env_in_place(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("ALPHA=1\nBETA=2\nGAMMA=3\n", encoding="utf-8")
        example = tmp_path / ".env.example"
        example.write_text("unused\n", encoding="utf-8")

        with mock.patch.object(demo, "ENV_PATH", env_path), mock.patch.object(
            demo, "ENV_EXAMPLE", example
        ):
            demo.write_env_file({"BETA": "updated"})

        content = env_path.read_text()
        assert "ALPHA=1" in content
        assert "BETA=updated" in content
        assert "GAMMA=3" in content

    def test_appends_missing_key(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("EXISTING=yes\n", encoding="utf-8")
        example = tmp_path / ".env.example"
        example.write_text("unused\n", encoding="utf-8")

        with mock.patch.object(demo, "ENV_PATH", env_path), mock.patch.object(
            demo, "ENV_EXAMPLE", example
        ):
            demo.write_env_file({"NEW_KEY": "new_val"})

        content = env_path.read_text()
        assert "EXISTING=yes" in content
        assert "NEW_KEY=new_val" in content

    def test_does_not_modify_commented_lines(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# FOO=old\nFOO=current\n", encoding="utf-8")
        example = tmp_path / ".env.example"
        example.write_text("unused\n", encoding="utf-8")

        with mock.patch.object(demo, "ENV_PATH", env_path), mock.patch.object(
            demo, "ENV_EXAMPLE", example
        ):
            demo.write_env_file({"FOO": "new"})

        content = env_path.read_text()
        assert "# FOO=old" in content
        assert "FOO=new" in content


# ---------------------------------------------------------------------------
# ensure_demo_datasource
# ---------------------------------------------------------------------------
class TestEnsureDemoDatasource:
    @pytest.fixture()
    def base_config(self):
        return {
            "datasources": {
                "World Bank Fraud and Integrity Reports": {
                    "data_subdir": "worldbank",
                    "field_mapping": {"title": "display_title"},
                    "example_queries": ["original query"],
                    "pipeline": {
                        "download": {"command": "old.py"},
                        "index": {"dense_models": ["azure_small", "e5_large"]},
                        "summarize": {
                            "dense_model": "e5_large",
                            "llm_model": {
                                "model": "Qwen/Qwen2.5-7B-Instruct",
                                "provider": "huggingface",
                            },
                        },
                        "tag": {
                            "dense_model": "e5_large",
                            "llm_model": {
                                "model": "Qwen/Qwen2.5-7B-Instruct",
                                "provider": "huggingface",
                            },
                        },
                    },
                }
            }
        }

    def test_adds_demo_datasource_with_azure(self, base_config):
        combo = demo.PROVIDER_COMBOS[0]  # Azure
        result = demo.ensure_demo_datasource(base_config, combo)

        assert result is True
        ds = base_config["datasources"][demo.DEMO_DATASOURCE_KEY]
        assert ds["data_subdir"] == "demo"
        assert ds["pipeline"]["index"]["dense_models"] == ["azure_small"]
        assert ds["pipeline"]["summarize"]["llm_model"]["model"] == "gpt-4.1-mini"
        assert ds["pipeline"]["tag"]["llm_model"]["provider"] == "azure_foundry"

    def test_adds_demo_datasource_with_huggingface(self, base_config):
        combo = demo.PROVIDER_COMBOS[1]  # HF
        result = demo.ensure_demo_datasource(base_config, combo)

        assert result is True
        ds = base_config["datasources"][demo.DEMO_DATASOURCE_KEY]
        assert ds["pipeline"]["index"]["dense_models"] == ["e5_large"]
        assert (
            ds["pipeline"]["summarize"]["llm_model"]["model"]
            == "Qwen/Qwen2.5-7B-Instruct"
        )
        assert ds["pipeline"]["summarize"]["llm_model"]["provider"] == "huggingface"

    def test_adds_demo_datasource_with_google(self, base_config):
        combo = demo.PROVIDER_COMBOS[2]  # Google
        result = demo.ensure_demo_datasource(base_config, combo)

        assert result is True
        ds = base_config["datasources"][demo.DEMO_DATASOURCE_KEY]
        assert ds["pipeline"]["index"]["dense_models"] == ["google_gemini_1536"]
        assert ds["pipeline"]["summarize"]["llm_model"]["model"] == "gemini-2.5-flash"

    def test_skips_if_already_exists(self, base_config):
        base_config["datasources"][demo.DEMO_DATASOURCE_KEY] = {"existing": True}
        combo = demo.PROVIDER_COMBOS[0]
        result = demo.ensure_demo_datasource(base_config, combo)
        assert result is False

    def test_sets_demo_download_command(self, base_config):
        combo = demo.PROVIDER_COMBOS[0]
        demo.ensure_demo_datasource(base_config, combo)
        ds = base_config["datasources"][demo.DEMO_DATASOURCE_KEY]
        assert ds["pipeline"]["download"]["command"] == "scripts/demo/download.py"

    def test_sets_example_queries(self, base_config):
        combo = demo.PROVIDER_COMBOS[0]
        demo.ensure_demo_datasource(base_config, combo)
        ds = base_config["datasources"][demo.DEMO_DATASOURCE_KEY]
        assert len(ds["example_queries"]) == 2
        assert "fraud" in ds["example_queries"][0].lower()

    def test_does_not_mutate_worldbank_config(self, base_config):
        import copy

        original_wb = copy.deepcopy(
            base_config["datasources"]["World Bank Fraud and Integrity Reports"]
        )
        combo = demo.PROVIDER_COMBOS[0]
        demo.ensure_demo_datasource(base_config, combo)
        assert (
            base_config["datasources"]["World Bank Fraud and Integrity Reports"]
            == original_wb
        )

    def test_exits_if_no_worldbank(self):
        config = {"datasources": {"other": {"data_subdir": "other"}}}
        combo = demo.PROVIDER_COMBOS[0]
        with pytest.raises(SystemExit):
            demo.ensure_demo_datasource(config, combo)


# ---------------------------------------------------------------------------
# prompt_provider
# ---------------------------------------------------------------------------
class TestPromptProvider:
    def test_default_selects_azure(self):
        with mock.patch("builtins.input", return_value=""):
            result = demo.prompt_provider()
        assert result["name"] == "Azure Foundry"

    def test_select_huggingface(self):
        with mock.patch("builtins.input", return_value="2"):
            result = demo.prompt_provider()
        assert result["name"] == "Huggingface / Together"

    def test_select_google(self):
        with mock.patch("builtins.input", return_value="3"):
            result = demo.prompt_provider()
        assert result["name"] == "Google Vertex"

    def test_invalid_then_valid(self):
        with mock.patch("builtins.input", side_effect=["99", "abc", "1"]):
            result = demo.prompt_provider()
        assert result["name"] == "Azure Foundry"


# ---------------------------------------------------------------------------
# prompt_api_keys
# ---------------------------------------------------------------------------
class TestPromptApiKeys:
    def test_collects_azure_keys(self):
        combo = demo.PROVIDER_COMBOS[0]
        with mock.patch("builtins.input", side_effect=["my-key", "https://endpoint"]):
            result = demo.prompt_api_keys(combo)
        assert result["AZURE_FOUNDRY_KEY"] == "my-key"
        assert result["AZURE_FOUNDRY_ENDPOINT"] == "https://endpoint"

    def test_retries_on_empty(self):
        combo = demo.PROVIDER_COMBOS[1]  # HF — one key
        with mock.patch("builtins.input", side_effect=["", "", "hf-token"]):
            result = demo.prompt_api_keys(combo)
        assert result["HUGGINGFACE_API_KEY"] == "hf-token"  # pragma: allowlist secret

    def test_google_shows_instructions(self):
        combo = demo.PROVIDER_COMBOS[2]  # pragma: allowlist secret
        with mock.patch("builtins.input", return_value=""):
            result = demo.prompt_api_keys(combo)
        assert result == {}


# ---------------------------------------------------------------------------
# prompt_qdrant_key
# ---------------------------------------------------------------------------
class TestPromptQdrantKey:
    def test_auto_generates_when_blank(self):
        with mock.patch("builtins.input", return_value=""):
            result = demo.prompt_qdrant_key()
        assert len(result) == 64  # hex of 32 bytes

    def test_uses_provided_value(self):
        with mock.patch("builtins.input", return_value="my-qdrant-key"):
            result = demo.prompt_qdrant_key()
        assert result == "my-qdrant-key"


# ---------------------------------------------------------------------------
# PROVIDER_COMBOS structure
# ---------------------------------------------------------------------------
class TestProviderCombos:
    def test_all_combos_have_required_fields(self):
        required = {
            "name",
            "description",
            "embedding_model",
            "dense_models",
            "summarize_dense",
            "llm_model_id",
            "llm_provider",
            "reranker",
            "required_env",
            "env_prompts",
        }
        for combo in demo.PROVIDER_COMBOS:
            missing = required - set(combo.keys())
            assert not missing, f"{combo['name']} missing: {missing}"

    def test_env_prompts_match_required_env(self):
        for combo in demo.PROVIDER_COMBOS:
            assert set(combo["env_prompts"].keys()) == set(
                combo["required_env"]
            ), f"{combo['name']}: env_prompts keys don't match required_env"

    def test_dense_models_is_list(self):
        for combo in demo.PROVIDER_COMBOS:
            assert isinstance(combo["dense_models"], list)
            assert len(combo["dense_models"]) >= 1
