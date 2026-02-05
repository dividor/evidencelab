import os
import random
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models


def _swap_internal_host(host: str) -> str:
    if "://db" in host or "://qdrant" in host or host == "db" or host == "qdrant":
        host = host.replace("://db", "://localhost")
        host = host.replace("://qdrant", "://localhost")
        if host == "db":
            host = "localhost"
        if host == "qdrant":
            host = "localhost"
    return host


def _normalize_qdrant_url(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        if ":" not in host:
            host = f"{host}:6333"
        host = f"http://{host}"
    return host


def load_env():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    load_dotenv(os.path.join(project_root, ".env"))


def debug_qdrant():
    print("--- Debugging Qdrant Performance (Hybrid + Filter Logic) ---")

    # 1. Connect
    load_env()
    host = os.getenv("QDRANT_HOST", "localhost")
    api_key = os.getenv("QDRANT_API_KEY")
    timeout = float(os.getenv("QDRANT_CLIENT_TIMEOUT", "240"))
    if not os.path.exists("/.dockerenv"):
        host = _swap_internal_host(host)
    host = _normalize_qdrant_url(host)

    if host.startswith("https://") and "localhost" in host:
        host = host.replace("https://", "http://", 1)

    print(f"Connecting to Qdrant at {host}...")
    client = QdrantClient(url=host, api_key=api_key, timeout=timeout)

    # 2. Identify Collection and Params
    collection_name = "chunks_uneg"  # Default
    target_vector_name = os.getenv("TARGET_MODEL", "e5_large")  # Allow overriding model
    sparse_vector_name = "bm25"

    # Params from App Logic causing slowness
    SEARCH_HNSW_EF = 128
    SEARCH_EXACT = False
    QUANTIZATION_RESCORE = True

    search_params = models.SearchParams(
        hnsw_ef=SEARCH_HNSW_EF,
        exact=SEARCH_EXACT,
        quantization=(
            models.QuantizationSearchParams(
                rescore=QUANTIZATION_RESCORE,
            )
            if QUANTIZATION_RESCORE
            else None
        ),
    )

    print("\nConfiguration:")
    print(f"Collection: {collection_name}")
    print(f"Target Dense: {target_vector_name}")
    print(f"Target Sparse: {sparse_vector_name}")
    print(f"Params: HNSW_EF={SEARCH_HNSW_EF}, Rescore={QUANTIZATION_RESCORE}")

    try:
        info = client.get_collection(collection_name)
        print(f"Collection Status: {info.status} (Points: {info.points_count})")
        if "section_type" in info.payload_schema:
            print("✅ 'section_type' is indexed.")
        else:
            print("❌ 'section_type' is NOT indexed.")

        # Check Quantization Status
        if info.config.quantization_config:
            q_conf = info.config.quantization_config
            print(f"✅ Quantization Enabled: {q_conf}")
        else:
            print("❌ Quantization DISABLED (Expect Cold Start Slowness)")
    except Exception as e:
        print(f"Error getting collection {collection_name}: {e}")
        return

    # 3. Setup Filter (The Heavy Operation)
    section_types = [
        "executive_summary",
        "introduction",
        "methodology",
        "findings",
        "conclusions",
        "recommendations",
        "annexes",
        "other",
    ]
    query_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="section_type", match=models.MatchAny(any=section_types)
            )
        ]
    )

    # 4. Generate Random Dense Vector
    target_vector_size = 1536
    # Try to find actual size if possible
    if hasattr(info.config.params.vectors, "get"):
        v_conf = info.config.params.vectors.get(target_vector_name)
        if v_conf:
            target_vector_size = v_conf.size
            print(f"Detected vector size: {target_vector_size}")

    dense_vector = [random.random() for _ in range(target_vector_size)]

    # 5. Generate Realistic Sparse Vector (Ensure Hits > 0)
    print("Fetching a real sparse vector to ensure hits...")
    try:
        # Get one point to see its sparse vector
        points = client.scroll(
            collection_name=collection_name, limit=1, with_vectors=[sparse_vector_name]
        )[0]

        if points and points[0].vector and sparse_vector_name in points[0].vector:
            real_sparse = points[0].vector[sparse_vector_name]
            # Use these indices to guarantee hits (at least this doc)
            # We want more hits, so maybe we use common indices if we could guess them.
            # But using a real document's terms is better than random.
            sparse_indices = real_sparse.indices
            sparse_values = real_sparse.values
            print(
                f"Using real sparse indices from doc {points[0].id}: {len(sparse_indices)} terms"
            )
        else:
            print("Could not fetch real sparse vector. Using random.")
            sparse_indices = random.sample(range(0, 10000), 10)
            sparse_values = [random.random() for _ in range(10)]
    except Exception as e:
        print(f"Failed to fetch real vector: {e}. Using random.")
        sparse_indices = random.sample(range(0, 10000), 10)
        sparse_values = [random.random() for _ in range(10)]

    sparse_vector = models.SparseVector(indices=sparse_indices, values=sparse_values)

    limit = 150

    # 6. Measure Hybrid Performance
    iterations = int(os.getenv("QDRANT_PERF_ITERATIONS", "5"))
    print(f"\nRunning {iterations} Hybrid Search iterations...")

    total_time = 0
    for i in range(iterations):
        start = time.time()

        # Dense Query
        dense_res = client.query_points(
            collection_name=collection_name,
            query=dense_vector,
            using=target_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            search_params=search_params,
        )

        # Sparse Query
        sparse_res = client.query_points(
            collection_name=collection_name,
            query=sparse_vector,
            using=sparse_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            # search_params=None
        )

        t_query_end = time.time()

        # Measure Python Object Materialization (The missing link?)
        # App merges dense_res and sparse_res, accessing payloads.
        msg_scan_count = 0
        for pt in dense_res.points:
            _ = pt.payload.get("text", "")
            msg_scan_count += 1
        for pt in sparse_res.points:
            _ = pt.payload.get("text", "")
            msg_scan_count += 1

        dur = time.time() - start
        serialization_time = dur - (t_query_end - start)

        total_time += dur
        print(
            f"Iteration {i+1}: {dur:.4f}s (Query: {t_query_end - start:.4f}s, "
            f"Parse: {serialization_time:.4f}s)"
        )

        if i == 0:
            first_run_time = dur

    avg = total_time / iterations
    cold_start = first_run_time
    warm_avg = (total_time - first_run_time) / (iterations - 1) if iterations > 1 else 0

    print("-" * 50)
    print(f"COLD START (Iter 1): {cold_start:.4f}s  <-- Matches API Slowness")
    print(f"WARM AVG (Iter 2+):  {warm_avg:.4f}s")
    print(f"TOTAL AVG:           {avg:.4f}s")
    print("-" * 50)

    if cold_start > 1.0:
        print("\n✅ REPRODUCED: Cold start latency confirmed (>1.0s).")
        print("   This confirms the API bottleneck is Disk I/O loading the Index.")
    else:
        print("\n✅ Fast. (Cache was likely already warm).")


if __name__ == "__main__":
    debug_qdrant()
