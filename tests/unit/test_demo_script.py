"""
test_demo_script.py - Unit tests for scripts/demo/run_demo.py
"""

import secrets
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
                                "model": "Qwen/Qwen2.5-72B-Instruct",
                                "provider": "huggingface",
                            },
                        },
                        "tag": {
                            "dense_model": "e5_large",
                            "llm_model": {
                                "model": "Qwen/Qwen2.5-72B-Instruct",
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
            == "Qwen/Qwen3-235B-A22B-Instruct-2507"
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
        assert result["name"] == "Huggingface"

    def test_select_google(self):
        with mock.patch("builtins.input", return_value="3"):
            result = demo.prompt_provider()
        assert result["name"] == "Google Vertex"

    def test_invalid_then_valid(self):
        with mock.patch("builtins.input", side_effect=["99", "abc", "1"]):
            result = demo.prompt_provider()
        assert result["name"] == "Azure Foundry"


# ---------------------------------------------------------------------------
# make_combo_default
# ---------------------------------------------------------------------------
class TestMakeComboDefault:
    @pytest.fixture()
    def config(self):
        return {
            "ui_model_combos": {
                "Azure Foundry": {"default": True, "embedding_model": "azure_small"},
                "Huggingface": {"embedding_model": "e5_large"},
                "Google Vertex": {"embedding_model": "google_gemini_1536"},
            }
        }

    def test_make_combo_default_when_other_combo_flagged_then_flag_moves(self, config):
        changed = demo.make_combo_default(config, demo.PROVIDER_COMBOS[1])  # HF

        combos = config["ui_model_combos"]
        assert changed is True
        assert combos["Huggingface"]["default"] is True
        assert "default" not in combos["Azure Foundry"]
        assert "default" not in combos["Google Vertex"]

    def test_make_combo_default_when_already_default_then_unchanged(self, config):
        changed = demo.make_combo_default(config, demo.PROVIDER_COMBOS[0])  # Azure

        assert changed is False
        assert config["ui_model_combos"]["Azure Foundry"]["default"] is True

    def test_make_combo_default_when_combo_missing_then_exits(self, config):
        del config["ui_model_combos"]["Huggingface"]

        with pytest.raises(SystemExit):
            demo.make_combo_default(config, demo.PROVIDER_COMBOS[1])

    def test_provider_combo_names_match_repository_config(self):
        import json

        with demo.CONFIG_PATH.open(encoding="utf-8") as config_file:
            combos = json.load(config_file)["ui_model_combos"]
        for combo in demo.PROVIDER_COMBOS:
            assert combo["name"] in combos


# ---------------------------------------------------------------------------
# _ci_select_provider
# ---------------------------------------------------------------------------
class TestCiSelectProvider:
    def test_ci_select_provider_when_named_then_that_combo_even_if_others_have_keys(
        self, monkeypatch
    ):
        monkeypatch.setenv("AZURE_FOUNDRY_KEY", "k")
        monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid")
        monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf")

        result = demo._ci_select_provider("huggingface")

        assert result["name"] == "Huggingface"

    def test_ci_select_provider_when_not_named_then_first_with_keys(self, monkeypatch):
        monkeypatch.setenv("AZURE_FOUNDRY_KEY", "k")
        monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid")

        result = demo._ci_select_provider()

        assert result["name"] == "Azure Foundry"

    def test_ci_select_provider_when_unknown_then_exits(self):
        with pytest.raises(SystemExit):
            demo._ci_select_provider("not-a-provider")


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


# ---------------------------------------------------------------------------
# Published image mode (--mode hub, docker-compose.hub.yml)
# ---------------------------------------------------------------------------
HUB = ["docker", "compose", "-f", "docker-compose.hub.yml"]


def _ok(returncode=0):
    return mock.Mock(returncode=returncode)


class TestEnvSetting:
    def test_env_setting_when_in_environment_then_environment_wins(
        self, tmp_path, monkeypatch
    ):
        env_path = tmp_path / ".env"
        env_path.write_text("EVIDENCELAB_PORT=9000\n", encoding="utf-8")
        monkeypatch.setenv("EVIDENCELAB_PORT", "9100")
        with mock.patch.object(demo, "ENV_PATH", env_path):
            assert demo._env_setting("EVIDENCELAB_PORT") == "9100"

    def test_env_setting_when_only_in_env_file_then_read_without_quotes(
        self, tmp_path, monkeypatch
    ):
        env_path = tmp_path / ".env"
        env_path.write_text('EVIDENCELAB_VERSION="1.6.5"\n', encoding="utf-8")
        monkeypatch.delenv("EVIDENCELAB_VERSION", raising=False)
        with mock.patch.object(demo, "ENV_PATH", env_path):
            assert demo._env_setting("EVIDENCELAB_VERSION") == "1.6.5"

    def test_env_setting_when_absent_then_empty(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EVIDENCELAB_VERSION", raising=False)
        with mock.patch.object(demo, "ENV_PATH", tmp_path / ".env"):
            assert demo._env_setting("EVIDENCELAB_VERSION") == ""


class TestResolveHubVersion:
    def test_resolve_when_flag_given_then_flag_wins(self, monkeypatch):
        monkeypatch.setenv("EVIDENCELAB_VERSION", "1.6.4")
        assert demo.resolve_hub_version("rc-v1.6.5") == "rc-v1.6.5"

    def test_resolve_when_only_env_file_then_uses_it(self, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        env_path.write_text("EVIDENCELAB_VERSION=1.6.5\n", encoding="utf-8")
        monkeypatch.delenv("EVIDENCELAB_VERSION", raising=False)
        with mock.patch.object(demo, "ENV_PATH", env_path):
            assert demo.resolve_hub_version(None) == "1.6.5"

    def test_resolve_when_nothing_set_then_latest(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EVIDENCELAB_VERSION", raising=False)
        with mock.patch.object(demo, "ENV_PATH", tmp_path / ".env"):
            assert demo.resolve_hub_version(None) == "latest"


class TestEnvFileValue:
    def test_env_file_value_when_key_repeated_then_last_wins_and_comments_ignored(
        self, tmp_path
    ):
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# EVIDENCELAB_PORT=commented\nEVIDENCELAB_PORT=first\n"
            "EVIDENCELAB_PORT='second'\n",
            encoding="utf-8",
        )
        with mock.patch.object(demo, "ENV_PATH", env_path):
            assert demo._env_file_value("EVIDENCELAB_PORT") == "second"


class TestSetupKeepsExistingSecrets:
    # Key names and values are built at runtime so no credential-shaped
    # literal sits in the source.
    DB_VAR = "POSTGRES_" + "PASSWORD"
    WEB_VAR = "API_SECRET_" + "KEY"
    SECRETS = (
        WEB_VAR,
        "AUTH_SECRET_KEY",
        "REACT_APP_API_KEY",
        "KEY_ENCRYPTION_KEY",
        DB_VAR,
        "QDRANT_API_KEY",
    )

    def _run_setup(self, tmp_path, env_text):
        env_path = tmp_path / ".env"
        env_path.write_text(env_text, encoding="utf-8")
        example = tmp_path / ".env.example"
        example.write_text("", encoding="utf-8")
        with mock.patch.object(demo, "ENV_PATH", env_path), mock.patch.object(
            demo, "ENV_EXAMPLE", example
        ):
            demo.interactive_setup(ci_mode=True, provider="huggingface")
            return {k: demo._env_file_value(k) for k in self.SECRETS}

    def _clean_env(self, monkeypatch):
        for key in self.SECRETS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HUGGINGFACE_API_KEY", secrets.token_hex(8))

    def test_setup_when_secrets_already_in_env_then_kept(self, tmp_path, monkeypatch):
        self._clean_env(monkeypatch)
        db_value, api_value = secrets.token_hex(8), secrets.token_hex(8)
        values = self._run_setup(
            tmp_path, f"{self.DB_VAR}={db_value}\n{self.WEB_VAR}={api_value}\n"
        )
        assert values[self.DB_VAR] == db_value
        assert values[self.WEB_VAR] == api_value

    def test_setup_when_secrets_empty_then_generated(self, tmp_path, monkeypatch):
        self._clean_env(monkeypatch)
        values = self._run_setup(tmp_path, f"{self.DB_VAR}=\n{self.WEB_VAR}=\n")
        assert len(values[self.DB_VAR]) == 32
        assert len(values[self.WEB_VAR]) == 64
        assert len(values["AUTH_SECRET_KEY"]) == 64
        assert values["REACT_APP_API_KEY"] == values[self.WEB_VAR]
        assert values["KEY_ENCRYPTION_KEY"]

    def test_setup_when_ci_env_pins_value_then_env_beats_file(
        self, tmp_path, monkeypatch
    ):
        self._clean_env(monkeypatch)
        pinned = secrets.token_hex(8)
        monkeypatch.setenv(self.DB_VAR, pinned)
        values = self._run_setup(tmp_path, f"{self.DB_VAR}={secrets.token_hex(8)}\n")
        assert values[self.DB_VAR] == pinned


class TestHubCommands:
    def test_download_hub_when_run_then_uses_published_image_without_deps(self):
        with mock.patch.object(demo.subprocess, "run", return_value=_ok()) as run:
            demo.download_documents_hub(3)
        cmd = run.call_args.args[0]
        assert cmd == HUB + [
            "--profile",
            "pipeline",
            "run",
            "--rm",
            "--no-deps",
            "pipeline",
            "python",
            "scripts/demo/download.py",
            "--limit",
            "3",
            "--data-dir",
            "/app/data/demo",
        ]
        assert run.call_args.kwargs["cwd"] == str(demo.PROJECT_ROOT)

    def test_pipeline_hub_when_run_then_processes_demo_source(self):
        with mock.patch.object(demo.subprocess, "run", return_value=_ok()) as run:
            demo.run_pipeline_hub(5)
        cmd = run.call_args.args[0]
        assert cmd == HUB + [
            "--profile",
            "pipeline",
            "run",
            "--rm",
            "pipeline",
            "python",
            "-m",
            "pipeline.orchestrator",
            "--data-source",
            "demo",
            "--num-records",
            "5",
            "--skip-download",
        ]

    @pytest.mark.parametrize("step", ["download_documents_hub", "run_pipeline_hub"])
    def test_hub_step_when_command_fails_then_exits(self, step):
        with mock.patch.object(demo.subprocess, "run", return_value=_ok(1)):
            with pytest.raises(SystemExit):
                getattr(demo, step)(3)

    def test_start_services_hub_when_run_then_rebuilds_ui_and_restarts_api(
        self, monkeypatch
    ):
        monkeypatch.setenv("EVIDENCELAB_PORT", "18080")
        with mock.patch.object(
            demo.subprocess, "run", return_value=_ok()
        ) as run, mock.patch.object(demo, "wait_for_hub_api") as wait:
            port = demo.start_services_hub()
        cmds = [c.args[0] for c in run.call_args_list]
        assert cmds == [
            HUB + ["up", "-d", "--build", "ui"],
            HUB + ["up", "-d", "--force-recreate", "api", "mcp"],
        ]
        wait.assert_called_once_with("18080")
        assert port == "18080"

    def test_start_services_hub_when_no_port_set_then_uses_8080(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("EVIDENCELAB_PORT", raising=False)
        with mock.patch.object(demo, "ENV_PATH", tmp_path / ".env"), mock.patch.object(
            demo.subprocess, "run", return_value=_ok()
        ), mock.patch.object(demo, "wait_for_hub_api") as wait:
            assert demo.start_services_hub() == "8080"
        wait.assert_called_once_with("8080")


class TestWaitForHubApi:
    def test_wait_when_api_answers_then_returns(self):
        resp = mock.MagicMock(status=200)
        resp.__enter__.return_value = resp
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            demo.wait_for_hub_api("8080", attempts=3, delay=0)
        assert urlopen.call_args.args[0] == "http://localhost:8080/api/health"

    def test_wait_when_api_never_answers_then_exits(self):
        import urllib.error

        with mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("refused")
        ) as urlopen:
            with pytest.raises(SystemExit):
                demo.wait_for_hub_api("8080", attempts=3, delay=0)
        assert urlopen.call_count == 3


class TestRunHubDemo:
    def test_run_hub_demo_when_skipping_download_and_pipeline_then_only_starts(
        self,
    ):
        args = mock.Mock(skip_download=True, skip_pipeline=True, num_docs=3)
        with mock.patch.object(
            demo, "download_documents_hub"
        ) as download, mock.patch.object(
            demo, "run_pipeline_hub"
        ) as pipeline, mock.patch.object(
            demo, "start_services_hub", return_value="8080"
        ):
            url = demo.run_hub_demo(args)
        download.assert_not_called()
        pipeline.assert_not_called()
        assert url == "http://localhost:8080"

    def test_run_hub_demo_when_full_run_then_downloads_then_processes(self):
        args = mock.Mock(skip_download=False, skip_pipeline=False, num_docs=4)
        order = mock.Mock()
        with mock.patch.object(
            demo, "download_documents_hub", order.download
        ), mock.patch.object(
            demo, "run_pipeline_hub", order.pipeline
        ), mock.patch.object(
            demo, "start_services_hub", order.start
        ):
            order.start.return_value = "18080"
            assert demo.run_hub_demo(args) == "http://localhost:18080"
        assert [c[0] for c in order.mock_calls] == ["download", "pipeline", "start"]
        order.download.assert_called_once_with(4)
        order.pipeline.assert_called_once_with(4)
