"""Concurrent login + search test for multiple authenticated users.

Verifies that users can log in and perform searches simultaneously.
Runs INSIDE the api container so it can hit localhost:8000 directly.

Usage:
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml \
        exec api python scripts/performance/test_user_concurrent.py

Options:
    --base-url URL        API base URL (default: http://localhost:8000)
    --data-source SRC     Data source to search (default: wfp)
    --password PW         Password for all users (default: OEVb3taTest!)
    --limit N             Max search results per query (default: 10)
    --rerank              Enable reranking (default: off)
    --users EMAIL,...     Comma-separated emails (default: all OEV users)
"""

import argparse
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_USERS = [
    "aino.partanen@wfp.org",
    "barbara.pfister@wfp.org",
    "chiara.raccichini@wfp.org",
    "christoph.waldmeier@wfp.org",
    "francesca.bonino@wfp.org",
    "lucia.landasotomayor@wfp.org",
    "nicola.theunissen@wfp.org",
    "rachida.aouameur@wfp.org",
    "simona.beltrami@wfp.org",
    "simone.lombardini@wfp.org",
    "william.mcfall@wfp.org",
    "jeanprovidence.nzabonimpa@wfp.org",
    "lise.bendiksen@wfp.org",
    "nour.elshabassi@wfp.org",
]

QUERIES = [
    "food security evaluation",
    "nutrition programme impact",
    "emergency response effectiveness",
    "climate adaptation resilience",
    "refugee displacement crisis",
    "gender protection assessment",
    "supply chain logistics",
    "school feeding programme",
    "cash transfer evaluation",
    "capacity building partnership",
    "drought resilience monitoring",
    "humanitarian coordination",
    "livelihood recovery strategy",
    "water sanitation hygiene",
]


def login_user(
    base_url: str, email: str, password: str
) -> tuple[urllib.request.OpenerDirector | None, float, str | None]:
    """Login via cookie endpoint. Returns (opener, login_time, error)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    form_data = urllib.parse.urlencode(
        {"username": email, "password": password}
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/auth/cookie-login/login",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    t0 = time.perf_counter()
    try:
        opener.open(req, timeout=30)
        return opener, time.perf_counter() - t0, None
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)


def do_search(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    query: str,
    data_source: str,
    limit: int,
    rerank: bool,
) -> tuple[bool, int, float, str | None]:
    """Perform an authenticated search. Returns (ok, count, time, error)."""
    params = urllib.parse.urlencode(
        {
            "q": query,
            "data_source": data_source,
            "limit": str(limit),
            "rerank": str(rerank).lower(),
            "dense_weight": "0.8",
        }
    )
    req = urllib.request.Request(f"{base_url}/search?{params}")
    t0 = time.perf_counter()
    try:
        resp = opener.open(req, timeout=60)
        data = json.loads(resp.read())
        count = data.get("total", len(data.get("results", [])))
        return True, count, time.perf_counter() - t0, None
    except Exception as e:
        return False, 0, time.perf_counter() - t0, str(e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent user login + search test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--data-source", default="wfp")
    parser.add_argument("--password", default="OEVb3taTest!")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument(
        "--users",
        default=None,
        help="Comma-separated emails (default: all OEV users)",
    )
    args = parser.parse_args()

    emails = (
        [e.strip() for e in args.users.split(",") if e.strip()]
        if args.users
        else DEFAULT_USERS
    )

    # ---- Phase 1: Login all users sequentially ----
    print("=" * 65)
    print(f"PHASE 1: Sequential login ({len(emails)} users)")
    print("=" * 65)

    sessions: dict[str, urllib.request.OpenerDirector] = {}
    for email in emails:
        opener, lt, err = login_user(args.base_url, email, args.password)
        if err:
            print(f"  FAIL  {email:45s} ({lt:.2f}s) {err}")
        else:
            sessions[email] = opener
            print(f"  OK    {email:45s} ({lt:.2f}s)")

    print(f"\nLogged in: {len(sessions)}/{len(emails)}")

    if not sessions:
        print("\nNo successful logins — aborting search phase.")
        return

    # ---- Phase 2: All users search concurrently ----
    print(f"\n{'=' * 65}")
    print(f"PHASE 2: Concurrent search ({len(sessions)} users)")
    print("=" * 65)

    t_start = time.perf_counter()
    search_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures = {}
        for i, (email, opener) in enumerate(sessions.items()):
            q = QUERIES[i % len(QUERIES)]
            future = executor.submit(
                do_search,
                opener,
                args.base_url,
                q,
                args.data_source,
                args.limit,
                args.rerank,
            )
            futures[future] = (email, q)

        for future in as_completed(futures):
            email, query = futures[future]
            ok, count, st, err = future.result()
            search_results.append(
                {"email": email, "ok": ok, "count": count, "time": st, "error": err}
            )
            status = "OK" if ok else "FAIL"
            err_str = f" | {err}" if err else ""
            print(
                f"  {status:4s}  {email:45s} {count:3d} results "
                f'({st:.2f}s)  q="{query}"{err_str}'
            )

    total_search = time.perf_counter() - t_start
    searches_ok = sum(1 for r in search_results if r["ok"])
    avg_search = sum(r["time"] for r in search_results if r["ok"]) / max(searches_ok, 1)

    print(f"\n{'=' * 65}")
    print("SUMMARY")
    print("=" * 65)
    print(f"Logins:           {len(sessions)}/{len(emails)} succeeded")
    print(f"Searches:         {searches_ok}/{len(sessions)} succeeded")
    print(f"Results returned: {sum(r['count'] for r in search_results)} total")
    print(
        f"Concurrent wall:  {total_search:.2f}s for {len(sessions)} simultaneous searches"
    )
    print(f"Avg search time:  {avg_search:.2f}s per user")

    if len(sessions) == len(emails) and searches_ok == len(emails):
        print(f"\nAll {len(emails)} users can log in and search concurrently!")
    elif searches_ok == len(sessions):
        print(f"\nAll {len(sessions)} logged-in users searched successfully!")
    else:
        failed = [r["email"] for r in search_results if not r["ok"]]
        print(f"\nFailed searches: {failed}")


if __name__ == "__main__":
    main()
