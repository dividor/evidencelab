import argparse
import json
import random
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_SECTION_TYPES = [
    "executive_summary",
    "context",
    "methodology",
    "findings",
    "conclusions",
    "recommendations",
    "other",
]


def parse_bool(value: str) -> bool:
    value_lower = value.strip().lower()
    if value_lower in {"true", "1", "yes", "y"}:
        return True
    if value_lower in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def build_search_url(
    base_url: str,
    query: str,
    data_source: str,
    rerank: bool,
    dense_weight: float,
    recency_boost: bool,
    recency_weight: float,
    recency_scale_days: int,
    section_types: list[str],
    keyword_boost_short_queries: bool,
    min_chunk_size: int,
    limit: int,
    model: str | None,
    document_type: str | None,
    published_year: str | None,
) -> str:
    params = {
        "q": query,
        "limit": str(limit),
        "data_source": data_source,
        "dense_weight": str(dense_weight),
        "rerank": str(rerank).lower(),
        "recency_boost": str(recency_boost).lower(),
        "recency_weight": str(recency_weight),
        "recency_scale_days": str(recency_scale_days),
        "section_types": ",".join(section_types),
        "keyword_boost_short_queries": str(keyword_boost_short_queries).lower(),
    }
    if min_chunk_size > 0:
        params["min_chunk_size"] = str(min_chunk_size)
    if model:
        params["model"] = model
    if document_type:
        params["document_type"] = document_type
    if published_year:
        params["published_year"] = published_year

    query_string = urllib.parse.urlencode(params)
    return f"{base_url.rstrip('/')}/search?{query_string}"


def execute_request(url: str, timeout: float) -> tuple[int, float, str | None]:
    start_time = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            _ = response.read()
            duration = time.perf_counter() - start_time
            return response.status, duration, None
    except Exception as exc:
        duration = time.perf_counter() - start_time
        return 0, duration, str(exc)


def run_stress_test(
    base_url: str,
    data_source: str,
    queries: list[str],
    document_types: list[str],
    years: list[str],
    total_requests: int,
    concurrency: int,
    rerank: bool,
    dense_weight: float,
    recency_boost: bool,
    recency_weight: float,
    recency_scale_days: int,
    section_types: list[str],
    keyword_boost_short_queries: bool,
    min_chunk_size: int,
    limit: int,
    model: str | None,
    timeout: float,
) -> dict:
    urls: list[str] = []
    for _ in range(total_requests):
        query = random.choice(queries)
        document_type = random.choice(document_types) if document_types else None
        published_year = random.choice(years) if years else None
        urls.append(
            build_search_url(
                base_url=base_url,
                query=query,
                data_source=data_source,
                rerank=rerank,
                dense_weight=dense_weight,
                recency_boost=recency_boost,
                recency_weight=recency_weight,
                recency_scale_days=recency_scale_days,
                section_types=section_types,
                keyword_boost_short_queries=keyword_boost_short_queries,
                min_chunk_size=min_chunk_size,
                limit=limit,
                model=model,
                document_type=document_type,
                published_year=published_year,
            )
        )

    latencies: list[float] = []
    status_counts: Counter[int] = Counter()
    error_messages: Counter[str] = Counter()

    start_time = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(execute_request, url, timeout): url for url in urls}
        for future in as_completed(futures):
            status, duration, error = future.result()
            latencies.append(duration)
            status_counts[status] += 1
            if error:
                error_messages[error] += 1
    total_time = time.perf_counter() - start_time

    latency_sorted = sorted(latencies)
    p50 = (
        latency_sorted[int(0.50 * (len(latency_sorted) - 1))] if latency_sorted else 0.0
    )
    p95 = (
        latency_sorted[int(0.95 * (len(latency_sorted) - 1))] if latency_sorted else 0.0
    )
    avg = statistics.mean(latencies) if latencies else 0.0

    return {
        "requests": total_requests,
        "concurrency": concurrency,
        "rerank": rerank,
        "total_time_sec": total_time,
        "throughput_rps": (total_requests / total_time) if total_time > 0 else 0.0,
        "latency_avg_sec": avg,
        "latency_p50_sec": p50,
        "latency_p95_sec": p95,
        "status_counts": dict(status_counts),
        "error_messages": dict(error_messages),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stress test /search endpoint.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--data-source", required=True)
    parser.add_argument(
        "--queries", default="evaluation,food security,health,education"
    )
    parser.add_argument("--document-types", default="")
    parser.add_argument("--years", default="")
    parser.add_argument("--total-requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--rerank", type=parse_bool, default=True)
    parser.add_argument("--run-both", action="store_true")
    parser.add_argument("--dense-weight", type=float, default=0.8)
    parser.add_argument("--recency-boost", type=parse_bool, default=False)
    parser.add_argument("--recency-weight", type=float, default=0.15)
    parser.add_argument("--recency-scale-days", type=int, default=365)
    parser.add_argument("--section-types", default=",".join(DEFAULT_SECTION_TYPES))
    parser.add_argument("--keyword-boost-short-queries", type=parse_bool, default=True)
    parser.add_argument("--min-chunk-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    document_types = [d.strip() for d in args.document_types.split(",") if d.strip()]
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    section_types = [s.strip() for s in args.section_types.split(",") if s.strip()]

    runs = [args.rerank]
    if args.run_both:
        runs = [True, False]

    results = []
    for rerank in runs:
        result = run_stress_test(
            base_url=args.base_url,
            data_source=args.data_source,
            queries=queries,
            document_types=document_types,
            years=years,
            total_requests=args.total_requests,
            concurrency=args.concurrency,
            rerank=rerank,
            dense_weight=args.dense_weight,
            recency_boost=args.recency_boost,
            recency_weight=args.recency_weight,
            recency_scale_days=args.recency_scale_days,
            section_types=section_types,
            keyword_boost_short_queries=args.keyword_boost_short_queries,
            min_chunk_size=args.min_chunk_size,
            limit=args.limit,
            model=args.model,
            timeout=args.timeout,
        )
        results.append(result)
        print(
            "\n=== Stress Test Result ===\n"
            f"rerank: {result['rerank']}\n"
            f"requests: {result['requests']}\n"
            f"concurrency: {result['concurrency']}\n"
            f"total_time_sec: {result['total_time_sec']:.2f}\n"
            f"throughput_rps: {result['throughput_rps']:.2f}\n"
            f"latency_avg_sec: {result['latency_avg_sec']:.2f}\n"
            f"latency_p50_sec: {result['latency_p50_sec']:.2f}\n"
            f"latency_p95_sec: {result['latency_p95_sec']:.2f}\n"
            f"status_counts: {result['status_counts']}\n"
            f"error_messages: {list(result['error_messages'].keys())[:5]}"
        )

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)


if __name__ == "__main__":
    main()
