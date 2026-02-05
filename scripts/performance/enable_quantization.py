import os

from qdrant_client import QdrantClient
from qdrant_client.http import models


def enable_quantization():
    print("--- Enabling Scalar Quantization (INT8) ---")

    # 1. Connect
    # If running in docker (api container), host is 'qdrant'
    # If running on host, it is 'localhost'
    host = os.getenv("QDRANT_HOST", "localhost")
    if "http" not in host:
        host = f"http://{host}"

    # If running inside API container (where QDRANT_HOST=http://qdrant:6333), this works.
    # If running on host (where QDRANT_HOST=http://localhost:6333), this works.

    print(f"Connecting to: {host}")
    client = QdrantClient(url=host)
    collection_name = "chunks_uneg"

    # 2. Define Scalar Quantization Config
    # INT8 compression. Always RAM. Rescore=True for precision.
    quant_config = models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8, quantile=0.99, always_ram=True
        )
    )

    # 3. Apply Update
    print("Applying update... (This triggers background re-indexing)")
    try:
        client.update_collection(
            collection_name=collection_name, quantization_config=quant_config
        )
        print("✅ Success! Quantization enabled.")
        print("Qdrant is now compressing vectors in the background.")
        print("Monitor CPU usage or wait a few minutes before benchmarking again.")
    except Exception as e:
        print(f"❌ Failed: {e}")


if __name__ == "__main__":
    enable_quantization()
