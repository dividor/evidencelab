import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

# Load environment variables from .env file
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)


def check_config():
    print("--- Qdrant Collection Config Inspector ---")

    # 1. Connect
    host = os.getenv("QDRANT_HOST", "localhost:6333")
    if "http" not in host:
        host = f"http://{host}"

    # Replace 'qdrant' (Docker hostname) with 'localhost' when running from host
    host = host.replace("://qdrant:", "://localhost:")

    api_key = os.getenv("QDRANT_API_KEY")

    print(f"Connecting to: {host}")
    client = QdrantClient(url=host, api_key=api_key)

    collection_name = "chunks_uneg"
    print(f"Collection: {collection_name}")

    try:
        info = client.get_collection(collection_name)

        # 1. Vector Params (On Disk?)
        vectors_config = info.config.params.vectors
        if isinstance(vectors_config, dict):
            for name, conf in vectors_config.items():
                print(f"[Vector: {name}]")
                print(f"  - Size: {conf.size}")
                # on_disk might be None (default) or True/False
                print(
                    f"  - On Disk: {conf.on_disk} (Default is False usually, but check memmap)"
                )
                # Datatype
                print(f"  - Datatype: {conf.datatype}")

        # 2. Quantization Config
        quant_config = info.config.quantization_config
        print("\n[Quantization]")
        if quant_config:
            print(f"  - Type: {type(quant_config)}")
            print(f"  - Config: {quant_config}")
        else:
            print("  - Status: DISABLED")

        # 3. HNSW Config
        print("\n[HNSW Config]")
        print(f"  - M: {info.config.hnsw_config.m}")
        print(f"  - EF Construct: {info.config.hnsw_config.ef_construct}")
        print(f"  - On Disk: {info.config.hnsw_config.on_disk}")

        # 4. Points
        print("\n[Stats]")
        print(f"  - Points: {info.points_count}")
        print(f"  - Segments: {info.segments_count}")
        print(f"  - Status: {info.status}")
        print(f"  - Optimizer Status: {info.optimizer_status}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    check_config()
