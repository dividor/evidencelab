import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import TypedDict

# Add project root to path to allow importing pipeline modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv  # noqa: E402

# Import UI_MODEL_COMBOS to get configured model suites
from pipeline.db import UI_MODEL_COMBOS  # noqa: E402


def load_env():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    load_dotenv(os.path.join(project_root, ".env"))


def build_headers() -> dict[str, str]:
    api_key = os.getenv("API_SECRET_KEY")
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def resolve_base_url() -> str:
    base_url = (
        os.getenv("API_BASE_URL")
        or os.getenv("REACT_APP_API_BASE_URL")
        or "http://localhost:8000"
    )
    if base_url.startswith("/"):
        base_url = f"http://localhost{base_url}"
    return base_url.rstrip("/")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _summarize_timings(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "min": min(values),
        "avg": statistics.fmean(values),
        "p50": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "max": max(values),
    }


TIMING_LABELS = {
    "Embedding generation": "embed",
    "Qdrant queries (hybrid)": "qdrant_hybrid",
    "search_chunks": "search_chunks",
    "rerank prepare_docs": "rerank prepare_docs",
    "rerank inference": "rerank inference",
    "rerank total": "rerank total",
    "title_doc_id_fetch": "title_doc_id_fetch",
    "doc_cache_fetch": "doc_cache_fetch",
    "chunk_cache_fetch": "chunk_cache_fetch",
    "search_chunks chunk_cache_fetch": "search_chunks chunk_cache_fetch",
    "search_chunks section_filter": "search_chunks section_filter",
    "search_chunks min_chunk_filter": "search_chunks min_chunk_filter",
    "search_chunks post_adjustments": "search_chunks post_adjustments",
    "batch_doc_fetch": "batch_doc_fetch",
    "build_results": "build_results",
    "doc_fetch+filter": "doc_fetch_filter",
    "TOTAL /search": "total_search",
}
TIMING_REGEX = re.compile(r"\[TIMING\]\s+([^:]+):\s+([0-9.]+)s")


class LogTimingReader:
    def __init__(
        self,
        path: str,
        encoding: str = "utf-8",
        wait_seconds: float = 2.0,
        poll_interval: float = 0.2,
    ) -> None:
        self.path = path
        self.encoding = encoding
        self.wait_seconds = wait_seconds
        self.poll_interval = poll_interval
        self.offset = 0
        self._init_offset()

    def _init_offset(self) -> None:
        if os.path.exists(self.path):
            self.offset = os.path.getsize(self.path)

    def _read_new_lines(self) -> list[str]:
        if not os.path.exists(self.path):
            return []
        size = os.path.getsize(self.path)
        if size < self.offset:
            self.offset = 0
        lines: list[str] = []
        with open(self.path, "r", encoding=self.encoding, errors="replace") as handle:
            handle.seek(self.offset)
            lines = handle.readlines()
            self.offset = handle.tell()
        return lines

    def snapshot(self) -> None:
        self._init_offset()

    def collect_timings(self) -> dict[str, float]:
        timings: dict[str, float] = {}
        start = time.time()
        while time.time() - start <= self.wait_seconds:
            lines = self._read_new_lines()
            if lines:
                timings.update(_extract_timings(lines))
            if "total_search" in timings:
                break
            time.sleep(self.poll_interval)
        return timings


class DockerTimingReader:
    def __init__(
        self,
        container: str,
        wait_seconds: float = 2.0,
        poll_interval: float = 0.2,
    ) -> None:
        self.container = container
        self.wait_seconds = wait_seconds
        self.poll_interval = poll_interval
        self.since_time: datetime | None = None

    def snapshot(self) -> None:
        self.since_time = datetime.now(timezone.utc)

    def _fetch_logs(self) -> list[str]:
        if not self.since_time:
            return []
        since = self.since_time.isoformat(timespec="seconds").replace("+00:00", "Z")
        result = subprocess.run(
            [
                "docker",
                "compose",
                "logs",
                "--no-color",
                "--since",
                since,
                self.container,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return result.stdout.splitlines()

    def collect_timings(self) -> dict[str, float]:
        timings: dict[str, float] = {}
        start = time.time()
        while time.time() - start <= self.wait_seconds:
            lines = self._fetch_logs()
            if lines:
                timings.update(_extract_timings(lines))
            if "total_search" in timings:
                break
            time.sleep(self.poll_interval)
        return timings


class PerfResult(TypedDict):
    combo: str
    mode: str
    query: str
    duration_avg: float
    duration_p50: float
    duration_p90: float
    headers_avg: float
    read_avg: float
    count: int
    log_stats: dict[str, dict[str, float]]


def _extract_timings(lines: list[str]) -> dict[str, float]:
    timings: dict[str, float] = {}
    for line in lines:
        match = TIMING_REGEX.search(line)
        if not match:
            continue
        label = match.group(1).strip()
        value = float(match.group(2))
        key = TIMING_LABELS.get(label)
        if key:
            timings[key] = value
    return timings


def _summarize_timing_map(
    timing_maps: list[dict[str, float]],
) -> dict[str, dict[str, float]]:
    values_by_key: dict[str, list[float]] = {}
    for timing_map in timing_maps:
        for key, value in timing_map.items():
            values_by_key.setdefault(key, []).append(value)
    return {key: _summarize_timings(values) for key, values in values_by_key.items()}


def _format_log_summary_lines(log_stats: dict[str, dict[str, float]]) -> list[str]:
    ordered_keys = [
        "total_search",
        "search_chunks",
        "embed",
        "qdrant_hybrid",
        "rerank prepare_docs",
        "rerank inference",
        "rerank total",
        "search_chunks chunk_cache_fetch",
        "search_chunks section_filter",
        "search_chunks min_chunk_filter",
        "search_chunks post_adjustments",
        "doc_cache_fetch",
        "chunk_cache_fetch",
        "build_results",
        "doc_fetch_filter",
    ]
    lines = []
    for key in ordered_keys:
        stats = log_stats.get(key)
        if not stats:
            continue
        label = "TOTAL" if key == "total_search" else key
        lines.append(f"{label}: avg={stats['avg']:.4f}s p90={stats['p90']:.4f}s")
    return lines


def test_endpoint(
    name: str,
    url: str,
    headers: dict[str, str],
    iterations: int = 1,
    log_reader: LogTimingReader | DockerTimingReader | None = None,
) -> tuple[
    dict[str, float],
    dict[str, float],
    dict[str, float],
    int,
    dict[str, dict[str, float]],
]:
    print(f"--- Testing {name} ---")
    print(f"URL: {url}")
    durations: list[float] = []
    header_times: list[float] = []
    read_times: list[float] = []
    counts: list[int] = []
    timing_maps: list[dict[str, float]] = []
    try:
        for i in range(iterations):
            if log_reader:
                log_reader.snapshot()
            start_time = time.time()
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request) as response:
                header_time = time.time()
                content = response.read()
                read_time = time.time()
                _ = json.loads(content)
                data = _ if isinstance(_, dict) else {}
                count = 0
                if name == "Stats":
                    # Stats endpoint doesn't return a list of items
                    pass
                elif "results" in data:
                    count = len(data["results"])
                    if count > 0:
                        first_title = data["results"][0].get("document_title") or data[
                            "results"
                        ][0].get("title", "Unknown")
                        print(f"First Result: {first_title}")
                elif "documents" in data:
                    count = len(data["documents"])
                    if count > 0:
                        first_doc = data["documents"][0]
                        first_title = first_doc.get("title") or first_doc.get(
                            "document_title", "Unknown"
                        )
                        print(f"First Result: {first_title}")
                else:
                    print(f"Unknown response format. Keys: {list(data.keys())}")

                durations.append(read_time - start_time)
                header_times.append(header_time - start_time)
                read_times.append(read_time - header_time)
                counts.append(count)

                if log_reader:
                    timing_maps.append(log_reader.collect_timings())

                if iterations > 1:
                    print(
                        f"Iteration {i + 1}/{iterations}: "
                        f"total={durations[-1]:.4f}s "
                        f"(headers={header_times[-1]:.4f}s, "
                        f"read={read_times[-1]:.4f}s)"
                    )

            if i == 0:
                print(f"Status Code: {response.getcode()}")

        if counts:
            print(f"Results Found: {counts[-1]}")

        total_stats = _summarize_timings(durations)
        header_stats = _summarize_timings(header_times)
        read_stats = _summarize_timings(read_times)
        log_stats = _summarize_timing_map(timing_maps)

        print(
            "Timing summary: "
            f"total avg={total_stats['avg']:.4f}s "
            f"(p50={total_stats['p50']:.4f}s, p90={total_stats['p90']:.4f}s), "
            f"headers avg={header_stats['avg']:.4f}s, "
            f"read avg={read_stats['avg']:.4f}s"
        )
        if log_reader:
            if log_stats:
                print("Log timings:")
                for line in _format_log_summary_lines(log_stats):
                    print(f"  - {line}")
            else:
                print("Log timings: none found (check log path and timing log level)")

        return (
            total_stats,
            header_stats,
            read_stats,
            (counts[-1] if counts else 0),
            log_stats,
        )
    except Exception as e:
        print(f"Request failed: {e}")
        return (
            {"min": 0.0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0},
            {"min": 0.0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0},
            {"min": 0.0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0},
            0,
            {},
        )


def test_search_performance(
    base_url: str | None = None,
    iterations: int = 1,
    log_path: str | None = None,
    docker_container: str | None = None,
    log_wait: float = 2.0,
    log_poll: float = 0.2,
    log_encoding: str = "utf-8",
    query: str = "evaluation",
):
    load_env()
    headers = build_headers()
    base_url = base_url or resolve_base_url()
    # base_url = "http://api:8000"
    log_reader: LogTimingReader | DockerTimingReader | None = None
    if docker_container is None and log_path is None:
        docker_container = "api"
    if docker_container:
        log_reader = DockerTimingReader(
            container=docker_container,
            wait_seconds=log_wait,
            poll_interval=log_poll,
        )
    elif log_path:
        log_reader = LogTimingReader(
            path=log_path,
            encoding=log_encoding,
            wait_seconds=log_wait,
            poll_interval=log_poll,
        )

    # 1. Test Stats (General Health)
    print("\n=== Checking System Health ===")
    test_endpoint(
        "Stats",
        f"{base_url}/stats?data_source=uneg",
        headers,
        iterations=iterations,
        log_reader=log_reader,
    )

    # 2. Identify configured model combos
    if not UI_MODEL_COMBOS:
        print("\n❌ No model combos found in UI_MODEL_COMBOS!")
        return

    print(f"\n=== Found {len(UI_MODEL_COMBOS)} Model Combos ===")
    for combo_name in UI_MODEL_COMBOS:
        print(f"  - {combo_name}")

    # 3. Test Search for EACH Combo (rerank on/off)
    # Use different queries per test to avoid any caching effects
    search_queries = [q.strip() for q in query.split(",") if q.strip()]
    if len(search_queries) < 2:
        search_queries = [
            search_queries[0] if search_queries else "evaluation",
            "food security",
            "climate change adaptation",
            "gender equality",
        ]

    results: list[PerfResult] = []
    query_idx = 0

    print("\n=== Benchmarking Search Performance ===")
    print(f"Query pool: {search_queries}")

    for combo_name, combo_config in UI_MODEL_COMBOS.items():
        embedding_model = combo_config.get("embedding_model")
        reranker_model = combo_config.get("reranker_model")
        sparse_model = combo_config.get("sparse_model")
        if not embedding_model:
            print(f"\n❌ Combo '{combo_name}' missing embedding_model")
            continue

        for rerank_enabled in (False, True):
            search_query = search_queries[query_idx % len(search_queries)]
            query_idx += 1
            mode_label = "rerank" if rerank_enabled else "no-rerank"
            print(f"\n>> Benchmarking Combo: {combo_name} ({mode_label}) q=\"{search_query}\"")
            params = {
                "q": search_query,
                "data_source": "uneg",
                "limit": 50,
                "section_types": (
                    "executive_summary,introduction,methodology,"
                    "findings,conclusions,recommendations,annexes,other"
                ),
                "model": embedding_model,
                "rerank": str(rerank_enabled).lower(),
            }
            if rerank_enabled and reranker_model:
                params["rerank_model"] = reranker_model
            if sparse_model:
                params["sparse_model"] = sparse_model
            query_string = urllib.parse.urlencode(params)
            total_stats, header_stats, read_stats, count, log_stats = test_endpoint(
                f"Search ({combo_name}, {mode_label})",
                f"{base_url}/search?{query_string}",
                headers,
                iterations=iterations,
                log_reader=log_reader,
            )
            results.append(
                {
                    "combo": combo_name,
                    "mode": mode_label,
                    "query": search_query,
                    "duration_avg": total_stats["avg"],
                    "duration_p50": total_stats["p50"],
                    "duration_p90": total_stats["p90"],
                    "headers_avg": header_stats["avg"],
                    "read_avg": read_stats["avg"],
                    "count": count,
                    "log_stats": log_stats,
                }
            )

    # Summary Report
    print("\n" + "=" * 95)
    header = (
        f"{'Combo':<25} | {'Mode':<10} | {'Query':<25} | {'Avg (s)':<9} | "
        f"{'P90 (s)':<9} | {'Hdr (s)':<8} | {'Read (s)':<9} | {'Docs':<6}"
    )
    print(header)
    print("-" * 95)
    for res in results:
        q_display = res["query"][:25]
        row = (
            f"{res['combo']:<25} | {res['mode']:<10} | "
            f"{q_display:<25} | "
            f"{res['duration_avg']:<9.4f} | {res['duration_p90']:<9.4f} | "
            f"{res['headers_avg']:<8.4f} | {res['read_avg']:<9.4f} | "
            f"{res['count']:<6}"
        )
        print(row)
    print("=" * 95)
    if log_reader:
        print("\n=== Log Timing Breakdown (avg/p90) ===")
        for res in results:
            log_stats = res["log_stats"]
            if not log_stats:
                print(f"{res['combo']} ({res['mode']}): no log timings found")
                continue
            print(f"{res['combo']} ({res['mode']}):")
            for line in _format_log_summary_lines(log_stats):
                print(f"  - {line}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify search performance")
    parser.add_argument(
        "--base-url",
        help="Base URL for the API (e.g. https://evidencelab.ai/api)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=int(os.getenv("SEARCH_PERF_ITERATIONS", "1")),
        help="Number of iterations per request (default: 1 or SEARCH_PERF_ITERATIONS)",
    )
    parser.add_argument(
        "--log-path",
        default=os.getenv("SEARCH_PERF_LOG_PATH"),
        help="Path to API log file to parse [TIMING] lines",
    )
    parser.add_argument(
        "--docker-container",
        default=os.getenv("SEARCH_PERF_DOCKER_CONTAINER"),
        help="Docker compose service name for API logs (default: api)",
    )
    parser.add_argument(
        "--log-wait",
        type=float,
        default=float(os.getenv("SEARCH_PERF_LOG_WAIT", "2.0")),
        help="Seconds to wait for timing logs after each request",
    )
    parser.add_argument(
        "--log-poll",
        type=float,
        default=float(os.getenv("SEARCH_PERF_LOG_POLL", "0.2")),
        help="Polling interval for log updates",
    )
    parser.add_argument(
        "--log-encoding",
        default=os.getenv("SEARCH_PERF_LOG_ENCODING", "utf-8"),
        help="Encoding for the log file (default: utf-8)",
    )
    parser.add_argument(
        "--query",
        default=os.getenv("SEARCH_PERF_QUERY", "evaluation"),
        help="Search query string (default: evaluation or SEARCH_PERF_QUERY)",
    )
    args = parser.parse_args()

    test_search_performance(
        base_url=args.base_url,
        iterations=args.iterations,
        log_path=args.log_path,
        docker_container=args.docker_container,
        log_wait=args.log_wait,
        log_poll=args.log_poll,
        log_encoding=args.log_encoding,
        query=args.query,
    )
