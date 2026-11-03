"""deploy/aws/scripts/demo_config.py writes the config for an AWS demo deployment.

It reuses the demo script's own setup, so the demo data source and model combo
on AWS match what ``scripts/demo/run_demo.py`` sets up locally. These tests run
the real helper on the repository's real config.json.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "deploy" / "aws" / "scripts" / "demo_config.py"

pytestmark = pytest.mark.unit


def _load_helper():
    spec = importlib.util.spec_from_file_location("aws_demo_config", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_config = _load_helper()
BASE_CONFIG = json.loads((REPO_ROOT / "config.json").read_text())


class TestBuildDemoConfig:
    def test_build_when_called_then_demo_is_the_only_data_source(self):
        config, _ = demo_config.build_demo_config(BASE_CONFIG, "azure_foundry")

        assert list(config["datasources"]) == [demo_config.run_demo.DEMO_DATASOURCE_KEY]

    def test_build_when_azure_foundry_then_adds_demo_source_and_its_keys(self):
        config, demo = demo_config.build_demo_config(BASE_CONFIG, "azure_foundry")

        source = config["datasources"][demo_config.run_demo.DEMO_DATASOURCE_KEY]
        assert source["data_subdir"] == demo["data_source"] == "demo"
        assert source["pipeline"]["download"]["command"] == "scripts/demo/download.py"
        assert demo["secret_names"] == ["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT"]

    def test_build_when_aws_bedrock_then_needs_no_secrets(self):
        _, demo = demo_config.build_demo_config(BASE_CONFIG, "aws_bedrock")

        assert demo["secret_names"] == []

    def test_build_when_huggingface_then_asks_for_its_token_only(self):
        _, demo = demo_config.build_demo_config(BASE_CONFIG, "huggingface")

        assert demo["secret_names"] == ["HUGGINGFACE_API_KEY"]

    def test_build_when_called_then_leaves_the_base_config_unchanged(self):
        before = json.dumps(BASE_CONFIG, sort_keys=True)

        demo_config.build_demo_config(BASE_CONFIG, "azure_foundry")

        assert json.dumps(BASE_CONFIG, sort_keys=True) == before

    def test_build_when_provider_unknown_then_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            demo_config.build_demo_config(BASE_CONFIG, "nope")


class TestMain:
    def test_main_when_run_then_writes_config_and_demo_settings(self, tmp_path):
        demo_config.main(["--provider", "azure_foundry", "--out-dir", str(tmp_path)])

        config = json.loads((tmp_path / "config.json").read_text())
        demo = json.loads((tmp_path / "demo.json").read_text())
        assert demo_config.run_demo.DEMO_DATASOURCE_KEY in config["datasources"]
        assert demo == {
            "data_source": "demo",
            "secret_names": ["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT"],
        }

    def test_main_when_run_then_keeps_progress_messages_off_stdout(
        self, tmp_path, capsys
    ):
        demo_config.main(["--provider", "azure_foundry", "--out-dir", str(tmp_path)])

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Demo Data from World Bank" in captured.err
