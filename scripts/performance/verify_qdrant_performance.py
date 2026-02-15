import os
import random
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Retry on connection failures (e.g. Qdrant still starting or wrong host)
QDRANT_CONNECT_RETRIES = int(os.getenv("QDRANT_CONNECT_RETRIES", "3"))
QDRANT_CONNECT_RETRY_DELAY = float(os.getenv("QDRANT_CONNECT_RETRY_DELAY", "2.0"))
# Short timeout for connect phase so we don't hang; full timeout used for benchmark after connect
QDRANT_CONNECT_TIMEOUT = float(os.getenv("QDRANT_CONNECT_TIMEOUT", "15.0"))


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


def _is_connection_error(exc: BaseException) -> bool:
    """True if the error is connection refused, reset, timeout, or similar (worth retrying)."""
    msg = str(exc).lower()
    if "connection refused" in msg or "connection reset" in msg:
        return True
    if "timeout" in msg or "timed out" in msg:
        return True
    if "errno 111" in msg or "errno 104" in msg:
        return True
    return False


def _host_candidates(primary: str) -> list[str]:
    """Build list of URLs to try: primary first, then localhost fallbacks when on host."""
    candidates = [primary]
    if not os.path.exists("/.dockerenv"):
        for fallback in ("http://127.0.0.1:6333", "http://localhost:6333"):
            if fallback not in candidates:
                candidates.append(fallback)
    return candidates


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

    collection_name = "chunks_uneg"  # Default
    target_vector_name = os.getenv("TARGET_MODEL", "e5_large")  # Allow overriding model
    sparse_vector_name = "bm25"

    # Connect with retries and fallbacks (e.g. Qdrant still starting, or try localhost on host)
    candidates = _host_candidates(host)
    client = None
    info = None
    last_error: Exception | None = None

    for try_url in candidates:
        if client is not None:
            break
        for attempt in range(1, QDRANT_CONNECT_RETRIES + 1):
            try:
                print(f"Connecting to Qdrant at {try_url}...")
                connect_client = QdrantClient(
                    url=try_url, api_key=api_key, timeout=QDRANT_CONNECT_TIMEOUT
                )
                info = connect_client.get_collection(collection_name)
                # Use full timeout for the benchmark
                client = QdrantClient(url=try_url, api_key=api_key, timeout=timeout)
                host = try_url
                break
            except Exception as e:
                last_error = e
                if _is_connection_error(e) and attempt < QDRANT_CONNECT_RETRIES:
                    print(
                        f"  Connection failed ({e}), retrying in {QDRANT_CONNECT_RETRY_DELAY}s..."
                    )
                    time.sleep(QDRANT_CONNECT_RETRY_DELAY)
                else:
                    if try_url != candidates[-1]:
                        print(f"  {e}, trying next host...")
                    break
        if client is not None:
            break
        else:
            client = None

    if client is None or info is None:
        print(f"Error getting collection {collection_name}: {last_error}")
        return

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
