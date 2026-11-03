"""Write the config.json for a demo deployment, with the World Bank demo data.

Uses the demo script's own setup (scripts/demo/run_demo.py): the chosen model
provider's combo becomes the default, and the "Demo Data from World Bank" data
source is added. It is the only data source in the result, so the site opens
on it and lists no empty datasets. Writes two files to --out-dir:

  config.json        the configuration to deploy and to build the web app with
  demo.json          {"data_source": ..., "secret_names": [...]}: the pipeline
                     data source and the provider settings the containers need

Usage: python3 deploy/aws/scripts/demo_config.py --provider azure_foundry --out-dir deploy/aws/.demo
"""

import argparse
import contextlib
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_run_demo():
    """Load scripts/demo/run_demo.py, which is a script rather than a package."""
    spec = importlib.util.spec_from_file_location(
        "run_demo", REPO_ROOT / "scripts" / "demo" / "run_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_demo = _load_run_demo()

PROVIDERS = [combo["llm_provider"] for combo in run_demo.PROVIDER_COMBOS]


def build_demo_config(base_config, provider):
    """Return (config, demo settings) for a demo deployment using ``provider``."""
    combo = next(
        (c for c in run_demo.PROVIDER_COMBOS if c["llm_provider"] == provider), None
    )
    if combo is None:
        raise ValueError(
            f"Unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}"
        )
    config = json.loads(json.dumps(base_config))
    # run_demo reports what it changes on stdout; keep that off ours.
    with contextlib.redirect_stdout(sys.stderr):
        run_demo.make_combo_default(config, combo)
        run_demo.ensure_demo_datasource(config, combo)
    key = run_demo.DEMO_DATASOURCE_KEY
    config["datasources"] = {key: config["datasources"][key]}
    demo = {
        "data_source": run_demo.DEMO_DATA_SUBDIR,
        "secret_names": list(combo["required_env"]),
    }
    return config, demo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", required=True, choices=PROVIDERS)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--base-config", type=Path, default=REPO_ROOT / "config.json")
    args = parser.parse_args(argv)

    config, demo = build_demo_config(
        json.loads(args.base_config.read_text()), args.provider
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (args.out_dir / "demo.json").write_text(json.dumps(demo) + "\n")


if __name__ == "__main__":
    main()
