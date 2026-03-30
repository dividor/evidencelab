#!/usr/bin/env python3
"""
smoke_test.py - Post-demo smoke tests for Evidence Lab services.

Checks that the UI, API, MCP server, A2A server, and search all respond
correctly after a demo run. Exits non-zero on any failure.

Usage:
    python scripts/demo/smoke_test.py
    API_URL=http://localhost:8000 MCP_URL=http://localhost:8001 python scripts/demo/smoke_test.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8001")
UI_URL = os.environ.get("UI_URL", "http://localhost:3000")
API_KEY = os.environ.get("API_SECRET_KEY", "")

# The demo datasource subdir written by run_demo.py
DEMO_DATA_SOURCE = "demo"

_failures = []


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)


def _post_json(url, data, headers=None):
    body = json.dumps(data).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def check(label, passed, detail=""):
    if passed:
        print(f"  [PASS] {label}")
    else:
        msg = f"  [FAIL] {label}"
        if detail:
            msg += f": {detail}"
        print(msg)
        _failures.append(label)


def main():
    auth = {"X-API-Key": API_KEY} if API_KEY else {}

    print()
    print("=" * 60)
    print("  Evidence Lab - Smoke Tests")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # 1. API health
    # ------------------------------------------------------------------
    print("[1/5] API health...")
    status, body = _get(f"{API_URL}/health", headers=auth)
    check("API /health returns 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 2. UI serves
    # ------------------------------------------------------------------
    print("[2/5] UI...")
    status, _ = _get(UI_URL)
    check("UI serves HTTP 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 3. MCP server health
    # ------------------------------------------------------------------
    print("[3/5] MCP server...")
    status, body = _get(f"{MCP_URL}/health")
    check("MCP /health returns 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 4. Search returns results
    # ------------------------------------------------------------------
    print("[4/5] Search API...")
    status, body = _get(
        f"{API_URL}/search?q=corruption+investigation&data_source={DEMO_DATA_SOURCE}",
        headers=auth,
    )
    check("Search returns 200", status == 200, f"status={status}")
    if status == 200:
        body_json = json.loads(body) if isinstance(body, str) and body else {}
        results = body_json.get("results", [])
        check(
            "Search returns at least 1 result",
            len(results) > 0,
            f"got {len(results)} results",
        )
    print()

    # ------------------------------------------------------------------
    # 5. A2A research task
    # ------------------------------------------------------------------
    print("[5/5] A2A research task...")
    task_id = f"smoke-{int(time.time())}"
    status, body = _post_json(
        f"{MCP_URL}/a2a",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": "What is the main subject of this document collection?",
                        }
                    ],
                    "metadata": {"data_source": DEMO_DATA_SOURCE},
                },
            },
        },
        headers=auth,
    )
    check("A2A tasks/send returns 200", status == 200, f"status={status}")
    if status == 200:
        result = body.get("result", {})
        state = result.get("status", {}).get("state", "")
        check(
            "A2A task accepted (submitted/working/completed)",
            state in ("submitted", "working", "completed"),
            f"state={state!r}",
        )
    print()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if _failures:
        print("=" * 60)
        print(f"  {len(_failures)} test(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("=" * 60)
        print("  All smoke tests passed.")
        print("=" * 60)


if __name__ == "__main__":
    main()
