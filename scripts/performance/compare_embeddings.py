import logging
import os
import sys
import time

import requests
import torch
from dotenv import load_dotenv
from fastembed import TextEmbedding
from sentence_transformers import SentenceTransformer

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_current_memory_mb():
    """Get current resident memory usage in MB."""
    if sys.platform != "linux":
        try:
            import psutil

            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            try:
                import resource

                # MAC: ru_maxrss is bytes. Linux: kilobytes.
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
            except Exception:
                return 0

    try:
        with open("/proc/self/status") as f:
            for line in f:
                if "VmRSS" in line:
                    return int(line.split()[1]) / 1024
    except Exception:
        return 0
    return 0


def call_azure_foundry_embedding(endpoint, api_key, deploy_name, texts):
    """
    Call Azure Foundry Embedding API via requests.
    """
    # Construct URL
    # Endpoint provided: https://human-prod-openai.openai.azure.com/
    # Target: {endpoint}/openai/deployments/{deploy_name}/embeddings?api-version=2023-05-15
    base_url = endpoint.rstrip("/")
    url = (
        f"{base_url}/openai/deployments/{deploy_name}/embeddings?"
        "api-version=2023-05-15"
    )

    headers = {"Content-Type": "application/json", "api-key": api_key}

    # Azure usually takes input as array of strings
    payload = {
        "input": texts
        # "model": deploy_name # Often optional if deployment implies model
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    # Extract embeddings ensuring order
    # Response: {"data": [{"embedding": [...], "index": 0}, ...]}
    sorted_data = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in sorted_data]


def compare_models():
    # Sample data
    sentences = [
        "The quick brown fox jumps over the lazy dog.",
        "Le renard brun et rapide saute par-dessus le chien paresseux.",
        "El zorro marrón rápido salta sobre el perro perezoso.",
        "Der schnelle braune Fuchs springt über den faulen Hund.",
        "This is a test sentence for performance comparison.",
        "Artificial intelligence is transforming the world.",
        "L'intelligence artificielle transforme le monde.",
        "La inteligencia artificial está transformando el mundo.",
        "Künstliche Intelligenz verändert die Welt.",
        "Machine learning models require good data.",
    ] * 50  # 500 sentences total

    logger.info(f"Test dataset size: {len(sentences)} sentences")

    # Models configuration
    models_config = [
        {
            "name": "intfloat/multilingual-e5-large",
            "type": "fastembed",
            "prefix": "passage: ",
        },
        {
            "name": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            "type": "sbert",
            "prefix": "",
        },
        {"name": "text-embedding-3-small", "type": "azure", "prefix": ""},
        {"name": "text-embedding-3-large", "type": "azure", "prefix": ""},
    ]

    results = []

    for config in models_config:
        model_name = config["name"]
        model_type = config["type"]
        prefix = config.get("prefix", "")

        logger.info(f"Processing model: {model_name}...")

        # Memory baseline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        import gc

        gc.collect()

        mem_before = get_current_memory_mb()

        try:
            # Prepare data
            if prefix:
                test_sentences = [f"{prefix}{s}" for s in sentences]
            else:
                test_sentences = sentences

            load_time = 0
            encode_time = 0
            speed = 0

            # --- FastEmbed ---
            if model_type == "fastembed":
                logger.info("Values: Loading FastEmbed model...")
                start_time = time.time()
                model = TextEmbedding(model_name=model_name)
                load_time = time.time() - start_time
                logger.info(f"Ref: Loaded in {load_time:.4f}s")

                mem_after_load = get_current_memory_mb()

                logger.info("Action: Encoding...")
                start_time = time.time()
                _ = list(model.embed(test_sentences))
                encode_time = time.time() - start_time

            # --- SentenceTransformer ---
            elif model_type == "sbert":
                logger.info("Values: Loading SentenceTransformer model...")

                kwargs = {}
                hf_token = os.getenv("HUGGINGFACE_API_KEY")
                if hf_token:
                    kwargs["token"] = hf_token

                start_time = time.time()
                model = SentenceTransformer(model_name, **kwargs)
                load_time = time.time() - start_time
                logger.info(f"Ref: Loaded in {load_time:.4f}s")

                mem_after_load = get_current_memory_mb()

                logger.info("Action: Encoding...")
                start_time = time.time()
                _ = model.encode(test_sentences)
                encode_time = time.time() - start_time

            # --- Azure Foundry ---
            elif model_type == "azure":
                logger.info("Values: Preparing Azure Foundry request...")
                endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
                api_key = os.getenv("AZURE_FOUNDRY_KEY")

                if not endpoint:
                    raise ValueError("Missing AZURE_FOUNDRY_ENDPOINT in environment")
                if not api_key:
                    raise ValueError("Missing AZURE_FOUNDRY_KEY in environment")

                # Azure usage is purely API call, so 'load time' is essentially 0
                start_time = time.time()
                # Assuming deployment name matches model name as is common pattern
                deployment_name = model_name
                load_time = 0.001  # neglible

                mem_after_load = get_current_memory_mb()  # Should be same

                logger.info("Action: Encoding (Batch calls via HTTP)...")
                start_time = time.time()

                # Batch processing for API
                # Azure limit is often 16 inputs per batch
                batch_size = 16
                for i in range(0, len(test_sentences), batch_size):
                    batch = test_sentences[i : i + batch_size]
                    _ = call_azure_foundry_embedding(
                        endpoint, api_key, deployment_name, batch
                    )

                encode_time = time.time() - start_time

            # Calculate metrics
            speed = len(sentences) / encode_time
            mem_used_load = max(0, mem_after_load - mem_before)

            logger.info(
                f"Metrics: Time={encode_time:.4f}s, "
                f"Speed={speed:.2f} sent/s, Mem={mem_used_load:.2f}MB"
            )

            results.append(
                {
                    "model": model_name,
                    "load_time": load_time,
                    "encode_time": encode_time,
                    "speed": speed,
                    "memory_mb": mem_used_load,
                    "status": "Success",
                }
            )

            if "model" in locals() and model_type != "azure":
                del model

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception as e:
            logger.error(f"Failed to process {model_name}: {e}")
            results.append(
                {
                    "model": model_name,
                    "load_time": 0,
                    "encode_time": 0,
                    "speed": 0,
                    "memory_mb": 0,
                    "status": f"Failed: {str(e)[:50]}...",
                }
            )

    # --- Summary ---
    print("\n" + "=" * 140)
    print("PERFORMANCE SUMMARY")
    print("=" * 140)
    print(
        f"{'Model':<60} | {'Status':<15} | {'Load (s)':<10} | "
        f"{'Encode (s)':<10} | {'Speed (s/s)':<12} | {'Mem (MB)':<10}"
    )
    print("-" * 140)
    for res in results:
        print(
            f"{res['model']:<60} | {res['status']:<15} | "
            f"{res['load_time']:<10.4f} | {res['encode_time']:<10.4f} | "
            f"{res['speed']:<12.2f} | {res['memory_mb']:<10.2f}"
        )
    print("-" * 140)


if __name__ == "__main__":
    compare_models()
