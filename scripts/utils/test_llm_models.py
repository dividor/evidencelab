#!/usr/bin/env python3
"""
Test script to verify all supported LLM models work correctly.

Tests each model in supported_llms from config.json to ensure:
- Model strings are correct
- Inference providers work (for HuggingFace)
- Azure Foundry models work
- API keys are properly loaded from .env
- All models use get_llm() from llm_factory correctly
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import after sys.path modification
from langchain_core.messages import HumanMessage  # noqa: E402

from utils.llm_factory import get_llm  # noqa: E402

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except (ImportError, PermissionError):
    # If dotenv not available or permission denied, just use existing env vars
    pass

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    """Load config.json."""
    config_path = Path(__file__).parent.parent.parent / "config.json"
    with open(config_path) as f:
        return json.load(f)


def test_llm_model(
    model_key: str,
    model_config: Dict[str, Any],
    temperature: float = 0.1,
    max_tokens: int = 50,
) -> bool:
    """
    Test an LLM model using get_llm() from llm_factory.

    This uses the same code path as the actual pipeline/UI code.
    """
    try:
        # Get the actual model string and provider from config
        model = model_config.get("model")
        provider = model_config.get("provider", "huggingface")
        inference_provider = model_config.get("inference_provider")

        logger.info("  Testing using get_llm() from llm_factory...")
        logger.info(f"    Model key: {model_key}")
        logger.info(f"    Model: {model}")
        logger.info(f"    Provider: {provider}")
        logger.info(f"    Inference provider: {inference_provider}")
        logger.info(f"    Temperature: {temperature}, Max tokens: {max_tokens}")

        # Use get_llm() - this is what the actual code uses
        # Pass the model_key (get_llm will resolve it to actual model string)
        llm = get_llm(
            provider=provider,
            model=model_key,  # Pass the key, get_llm will resolve it
            temperature=temperature,
            max_tokens=max_tokens,
            inference_provider=inference_provider,
        )

        # Test the LLM
        response = llm.invoke([HumanMessage(content="Say 'test successful'")])
        result = str(response.content)[:50]
        logger.info(f"  ✓ Success: {result}")
        return True

    except Exception as e:
        logger.error(f"  ✗ Failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        return False


def main():
    """Test all supported LLM models from config.json."""
    logger.info("=" * 80)
    logger.info("Testing Supported LLM Models")
    logger.info("=" * 80)

    config = load_config()
    supported_llms = config.get("supported_llms", {})

    if not supported_llms:
        logger.error("No 'supported_llms' found in config.json")
        logger.error("Please ensure config.json has a 'supported_llms' section")
        return 1

    logger.info(f"Found {len(supported_llms)} model(s) to test:")
    for model_name in supported_llms.keys():
        logger.info(f"  - {model_name}")
    logger.info("")

    # Check API keys are available (for informational purposes)
    hf_api_key = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
    azure_api_key = os.getenv("AZURE_FOUNDRY_KEY")
    azure_endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")

    logger.info("API Key check:")
    logger.info(f"  HuggingFace API Key: {'Yes' if hf_api_key else 'No'}")
    logger.info(f"  Azure Foundry API Key: {'Yes' if azure_api_key else 'No'}")
    logger.info(f"  Azure Foundry Endpoint: {'Yes' if azure_endpoint else 'No'}")
    logger.info("")

    results = {}

    # Also load pipeline configs to get actual temperature/max_tokens for each model
    # This helps verify the config structure is correct
    datasources = config.get("datasources", {})
    pipeline_configs = {}
    for ds_name, ds_config in datasources.items():
        pipeline = ds_config.get("pipeline", {})
        # Get configs from toc_correction, summarize, tag
        for stage in ["parse", "summarize", "tag"]:
            stage_config = pipeline.get(stage, {})
            if stage == "parse":
                llm_config = stage_config.get("toc_correction", {}).get("llm_model", {})
            else:
                llm_config = stage_config.get("llm_model", {})

            if isinstance(llm_config, dict):
                model_key = llm_config.get("model")
                if model_key:
                    if model_key not in pipeline_configs:
                        pipeline_configs[model_key] = []
                    pipeline_configs[model_key].append(
                        {
                            "stage": stage,
                            "temperature": llm_config.get("temperature"),
                            "max_tokens": llm_config.get("max_tokens"),
                        }
                    )

    for model_key, model_config in supported_llms.items():
        logger.info("")
        logger.info(f"Testing: {model_key} (key from supported_llms)")
        logger.info(f"  Actual Model: {model_config.get('model')}")
        logger.info(f"  Provider: {model_config.get('provider')}")
        logger.info(
            f"  Inference Provider: {model_config.get('inference_provider', 'None')}"
        )

        # Get temperature and max_tokens from pipeline configs if available
        # Otherwise use defaults
        temperature = 0.1
        max_tokens = 50

        if model_key in pipeline_configs:
            # Use values from first pipeline config that uses this model
            pipeline_values = pipeline_configs[model_key][0]
            temperature = pipeline_values.get("temperature", temperature)
            max_tokens = pipeline_values.get("max_tokens", max_tokens)
            logger.info(
                f"  Using values from pipeline config: "
                f"temperature={temperature}, max_tokens={max_tokens}"
            )
        else:
            logger.info(
                f"  Using default test values: temperature={temperature}, max_tokens={max_tokens}"
            )

        # Test using get_llm() - this is what the actual code uses
        success = test_llm_model(model_key, model_config, temperature, max_tokens)

        results[model_key] = success

        if success:
            logger.info(f"  ✓ {model_key} test PASSED")
        else:
            logger.error(f"  ✗ {model_key} test FAILED")

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for model_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"{status}: {model_name}")

    logger.info("")
    logger.info(f"Total: {passed}/{total} passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
