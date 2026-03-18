#!/usr/bin/env python3
"""
run_demo.py - Interactive demo that guides you through provider setup,
downloads a few documents, and runs the full Evidence Lab pipeline.

Usage:
    python scripts/demo/run_demo.py --mode host
    python scripts/demo/run_demo.py --mode docker
    python scripts/demo/run_demo.py --mode host --setup   # Re-run setup

What it does:
    0. Interactive setup: choose provider, enter API keys, write .env
    1. Adds a "demo" datasource entry to config.json with your chosen models.
    2. Downloads documents from the World Bank API.
    3. Runs the full pipeline (on host or in Docker).
    4. Restarts the API so it picks up the new datasource.
"""

import argparse
import copy
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.json"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
ENV_PATH = PROJECT_ROOT / ".env"
DOWNLOAD_SCRIPT = PROJECT_ROOT / "scripts" / "demo" / "download.py"
HOST_PIPELINE_SCRIPT = PROJECT_ROOT / "scripts" / "pipeline" / "run_pipeline_host.sh"

DEMO_DATASOURCE_KEY = "Demo Data from World Bank"
DEMO_DATA_SUBDIR = "demo"

# ---------------------------------------------------------------------------
# Provider combo definitions
# ---------------------------------------------------------------------------
PROVIDER_COMBOS = [
    {
        "name": "Azure Foundry",
        "description": "Embedding: azure_small, LLM: gpt-4.1-mini, Reranker: Cohere",
        "embedding_model": "azure_small",
        "dense_models": ["azure_small"],
        "summarize_dense": "azure_small",
        "llm_model_id": "gpt-4.1-mini",
        "llm_provider": "azure_foundry",
        "reranker": "Cohere-rerank-v4.0-fast",
        "required_env": ["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT"],
        "env_prompts": {
            "AZURE_FOUNDRY_KEY": "Azure Foundry API key",
            "AZURE_FOUNDRY_ENDPOINT": "Azure Foundry endpoint URL",
        },
    },
    {
        "name": "Huggingface / Together",
        "description": "Embedding: e5_large (local), LLM: Qwen 2.5-7B, Reranker: Jina",
        "embedding_model": "e5_large",
        "dense_models": ["e5_large"],
        "summarize_dense": "e5_large",
        "llm_model_id": "Qwen/Qwen2.5-7B-Instruct",
        "llm_provider": "huggingface",
        "reranker": "jinaai/jina-reranker-v2-base-multilingual",
        "required_env": ["HUGGINGFACE_API_KEY"],
        "env_prompts": {
            "HUGGINGFACE_API_KEY": (
                "Huggingface API token (needs Inference Provider access)"
            ),
        },
    },
    {
        "name": "Google Vertex",
        "description": (
            "Embedding: google_gemini_1536, LLM: Gemini 2.5 Flash, "
            "Reranker: Vertex AI"
        ),
        "embedding_model": "google_gemini_1536",
        "dense_models": ["google_gemini_1536"],
        "summarize_dense": "google_gemini_1536",
        "llm_model_id": "gemini-2.5-flash",
        "llm_provider": "google_vertex",
        "reranker": "vertex-ai-ranker",
        "required_env": [],
        "env_prompts": {},
        "setup_instructions": ("Run: gcloud auth application-default login"),
    },
]


# ---------------------------------------------------------------------------
# Interactive setup
# ---------------------------------------------------------------------------
def _mask(value):
    """Mask all but the last 4 characters of a secret."""
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def prompt_provider():
    """Ask user to choose a provider combo."""
    print("Which provider would you like to use?\n")
    for i, combo in enumerate(PROVIDER_COMBOS, 1):
        rec = " (Recommended)" if i == 1 else ""
        print(f"  [{i}] {combo['name']}{rec}")
        print(f"      {combo['description']}")
        if combo["required_env"]:
            print(f"      Requires: {', '.join(combo['required_env'])}")
        if combo.get("setup_instructions"):
            print(f"      Setup: {combo['setup_instructions']}")
        print()

    while True:
        choice = input("Choice [1]: ").strip() or "1"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(PROVIDER_COMBOS):
                return PROVIDER_COMBOS[idx]
        except ValueError:
            pass
        print(f"  Please enter 1-{len(PROVIDER_COMBOS)}")


def prompt_api_keys(combo):
    """Prompt for the provider-specific API keys. Returns a dict."""
    collected = {}

    if combo.get("setup_instructions"):
        print(f"\n  Note: {combo['setup_instructions']}")
        input("  Press Enter when ready...")

    for env_var, description in combo["env_prompts"].items():
        while True:
            value = input(f"\n  {description}\n  {env_var}: ").strip()
            if value:
                collected[env_var] = value
                break
            print("  (required)")

    return collected


def prompt_qdrant_key():
    """Prompt for Qdrant API key, or auto-generate one."""
    value = input("\nQdrant API key (leave blank to auto-generate): ").strip()
    if not value:
        value = secrets.token_hex(32)
        print(f"  Generated: {_mask(value)}")
    return value


def interactive_setup():
    """Run the full interactive setup flow. Returns (combo, env_vars)."""
    print()
    print("=" * 60)
    print("  Evidence Lab - Interactive Setup")
    print("=" * 60)
    print()

    # 1. Provider selection
    combo = prompt_provider()
    print(f"\n  Selected: {combo['name']}\n")

    # 2. Provider-specific API keys
    env_vars = prompt_api_keys(combo)

    # 3. Qdrant API key
    env_vars["QDRANT_API_KEY"] = prompt_qdrant_key()

    # 4. Auto-generate API_SECRET_KEY and AUTH_SECRET_KEY
    env_vars["API_SECRET_KEY"] = secrets.token_hex(32)
    env_vars["AUTH_SECRET_KEY"] = secrets.token_hex(32)
    # Keep REACT_APP_API_KEY in sync with API_SECRET_KEY
    env_vars["REACT_APP_API_KEY"] = env_vars["API_SECRET_KEY"]
    print("  Auto-generated API_SECRET_KEY and AUTH_SECRET_KEY")

    # 5. Confirmation
    print()
    print("-" * 60)
    print("  Configuration summary:")
    print(f"  Provider:        {combo['name']}")
    for key, val in env_vars.items():
        if key in ("API_SECRET_KEY", "AUTH_SECRET_KEY", "REACT_APP_API_KEY"):
            print(f"  {key + ':':23s} [auto-generated]")
        elif key == "QDRANT_API_KEY" and len(val) == 64:
            print(f"  {key + ':':23s} [auto-generated]")
        else:
            print(f"  {key + ':':23s} {_mask(val)}")
    print("-" * 60)

    if ENV_PATH.exists():
        confirm = (
            input("\n  .env already exists. Update the above variables? [Y/n]: ")
            .strip()
            .lower()
        )
        if confirm in ("n", "no"):
            print("  Keeping existing .env unchanged")
            return combo, env_vars
    else:
        confirm = input("\n  Write to .env? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("  Skipped writing .env")
            return combo, env_vars

    # 6. Write .env
    write_env_file(env_vars)
    print(f"  Wrote {ENV_PATH}")
    return combo, env_vars


def write_env_file(env_vars):
    """Update .env with the provided values.

    If .env exists, only the specified keys are updated in-place (all other
    content is preserved). If .env does not exist, it is created from
    .env.example with the keys filled in.
    """
    if ENV_PATH.exists():
        content = ENV_PATH.read_text(encoding="utf-8")
    else:
        content = ENV_EXAMPLE.read_text(encoding="utf-8")

    for key, value in env_vars.items():
        # Match lines like KEY= or KEY=existing_value (not commented out)
        pattern = rf"^({re.escape(key)}\s*=)(.*)$"
        replacement = rf"\g<1>{value}"
        content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)
        if count == 0:
            # Key not found in file, append it
            content += f"\n{key}={value}\n"

    ENV_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------
def load_config():
    """Load the project config.json."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    """Write config.json back to disk."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


def ensure_demo_datasource(config, combo):
    """Add the demo datasource to config.json using the selected provider.

    Clones the World Bank datasource config and adjusts models, data_subdir,
    and download settings for demo use.
    """
    datasources = config.get("datasources", {})

    if DEMO_DATASOURCE_KEY in datasources:
        print(f"  '{DEMO_DATASOURCE_KEY}' datasource already exists in config.json")
        return False

    # Find World Bank config to clone
    wb_key = None
    for key in datasources:
        if datasources[key].get("data_subdir") == "worldbank":
            wb_key = key
            break

    if wb_key is None:
        print("ERROR: Could not find a World Bank datasource in config.json to clone.")
        sys.exit(1)

    demo_config = copy.deepcopy(datasources[wb_key])

    # Override data directory and queries
    demo_config["data_subdir"] = DEMO_DATA_SUBDIR
    demo_config["example_queries"] = [
        "What types of fraud are most commonly reported?",
        "How does the World Bank investigate allegations of corruption?",
    ]

    # Point download at the demo downloader
    demo_config["pipeline"]["download"] = {
        "command": "scripts/demo/download.py",
        "args": ["--data-dir", "{data_dir}", "--limit", "{num_records}"],
    }

    # Apply provider-specific model config
    pipeline = demo_config["pipeline"]

    # Index: dense models
    pipeline["index"]["dense_models"] = combo["dense_models"]

    # Summarize: LLM and dense model
    pipeline["summarize"]["dense_model"] = combo["summarize_dense"]
    pipeline["summarize"]["llm_model"] = {
        "model": combo["llm_model_id"],
        "provider": combo["llm_provider"],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    # Tag: LLM and dense model
    pipeline["tag"]["dense_model"] = combo["summarize_dense"]
    pipeline["tag"]["llm_model"] = {
        "model": combo["llm_model_id"],
        "provider": combo["llm_provider"],
        "temperature": 0.0,
        "max_tokens": 4000,
    }

    datasources[DEMO_DATASOURCE_KEY] = demo_config
    config["datasources"] = datasources
    print(f"  Added '{DEMO_DATASOURCE_KEY}' datasource to config.json")
    print(
        f"  Models: embedding={combo['embedding_model']}, "
        f"llm={combo['llm_model_id']}"
    )
    return True


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
def download_documents(num_docs):
    """Run the demo downloader to fetch documents."""
    data_dir = PROJECT_ROOT / "data" / DEMO_DATA_SUBDIR
    cmd = [
        sys.executable,
        str(DOWNLOAD_SCRIPT),
        "--limit",
        str(num_docs),
        "--data-dir",
        str(data_dir),
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("ERROR: Download failed.")
        sys.exit(1)


def run_pipeline_docker(num_docs):
    """Run the full pipeline inside the Docker pipeline container."""
    cmd = [
        "docker",
        "compose",
        "exec",
        "pipeline",
        "python",
        "-m",
        "pipeline.orchestrator",
        "--data-source",
        DEMO_DATA_SUBDIR,
        "--num-records",
        str(num_docs),
        "--skip-download",
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("ERROR: Pipeline failed. Are Docker services running?")
        print("       Try: docker compose up -d --build")
        sys.exit(1)


def run_pipeline_host(num_docs):
    """Run the full pipeline on the host using the local .venv."""
    cmd = [
        str(HOST_PIPELINE_SCRIPT),
        "--data-source",
        DEMO_DATA_SUBDIR,
        "--num-records",
        str(num_docs),
        "--skip-download",
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("ERROR: Pipeline failed.")
        print("       Check that infrastructure services are running:")
        print("       docker compose up -d qdrant postgres")
        sys.exit(1)


def start_services():
    """Start embedding server, API, and UI, then wait for the API to be ready."""
    import time
    import urllib.error
    import urllib.request

    # Ensure the Docker embedding server, API, and UI are running
    print("  Starting embedding-server, API, and UI...")
    subprocess.run(
        ["docker", "compose", "up", "-d", "embedding-server", "api", "ui"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    # Read API key from .env for health check
    api_key = ""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("API_SECRET_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

    print("  Waiting for API to become ready", end="", flush=True)
    for _ in range(90):
        time.sleep(2)
        print(".", end="", flush=True)
        try:
            req = urllib.request.Request(
                "http://localhost:8000/",
                headers={"X-API-Key": api_key} if api_key else {},
            )
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                print(" ready!")
                return
        except (urllib.error.URLError, OSError):
            pass
    print(" ready!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Run the Evidence Lab demo: interactive setup, download "
        "documents, and process them through the pipeline.",
    )
    parser.add_argument(
        "--mode",
        choices=["host", "docker"],
        default="host",
        help="Run pipeline on host (.venv) or in Docker (default: host)",
    )
    parser.add_argument(
        "--num-docs",
        type=int,
        default=3,
        help="Number of documents to download and process (default: 3)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading documents (use previously downloaded files)",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Skip running the pipeline (only download documents and add config)",
    )
    args = parser.parse_args()

    # Step 0: Interactive setup (always runs)
    combo, _ = interactive_setup()

    print()
    print("=" * 60)
    print(f"  Evidence Lab Demo (mode: {args.mode})")
    print("=" * 60)
    print()

    # Step 1: Ensure demo datasource in config.json
    print("[1/4] Configuring demo datasource...")
    config = load_config()
    changed = ensure_demo_datasource(config, combo)
    if changed:
        save_config(config)
    print()

    # Step 2: Download documents
    if args.skip_download:
        print("[2/4] Skipping download (--skip-download)")
    else:
        print(f"[2/4] Downloading {args.num_docs} documents from World Bank API...")
        download_documents(args.num_docs)
    print()

    # Step 3: Run pipeline
    if args.skip_pipeline:
        print("[3/4] Skipping pipeline (--skip-pipeline)")
    else:
        print(f"[3/4] Running pipeline on {args.num_docs} documents ({args.mode})...")
        if args.mode == "host":
            print(
                "       (Ensure infrastructure: docker compose up -d qdrant postgres)"
            )
            run_pipeline_host(args.num_docs)
        else:
            print("       (Ensure Docker: docker compose up -d --build)")
            run_pipeline_docker(args.num_docs)
    print()

    # Step 4: Start UI services (embedding server, API, UI) and wait for API
    print("[4/4] Starting services...")
    start_services()
    print()

    print("=" * 60)
    print("  Demo complete!")
    print()
    print("  Open http://localhost:3000 to explore the results.")
    print(f"  Select the '{DEMO_DATASOURCE_KEY}' data source in the UI.")
    print("=" * 60)


if __name__ == "__main__":
    main()
