#!/usr/bin/env python3
"""
smoke_test.py - Post-demo smoke tests for Evidence Lab services.

Checks the UI, API, MCP, A2A, search, Assistant and Brief generation after a demo run.
Exits non-zero on any failure.

Usage:
    python -m tests.integration.demo_smoke_test
    python -m tests.integration.demo_smoke_test
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from ui.backend.services.test_evaluators import eval_brief_length

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8001")
UI_URL = os.environ.get("UI_URL", "http://localhost:3000")
API_KEY = os.environ.get("API_SECRET_KEY", "")

# The demo datasource subdir written by run_demo.py
DEMO_DATA_SOURCE = "demo"

# The Assistant has 120 seconds to respond. Leave time for the HTTP response.
A2A_REQUEST_TIMEOUT_SECONDS = 135
RESEARCH_REQUEST_TIMEOUT_SECONDS = 240

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
        resp = urllib.request.urlopen(req, timeout=A2A_REQUEST_TIMEOUT_SECONDS)
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


def _research_events(combo, auth, **request_fields):
    payload = {
        "data_source": DEMO_DATA_SOURCE,
        "deep_research": True,
        "assistant_model_config": combo.get("assistant_model")
        or combo.get("summarization_model"),
        "search_settings": {"embedding_model": combo.get("embedding_model")},
        "reranker_model": combo.get("reranker_model"),
        **request_fields,
    }
    request = urllib.request.Request(
        f"{API_URL}/assistant/chat/stream",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **auth},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=RESEARCH_REQUEST_TIMEOUT_SECONDS
        ) as resp:
            return [json.loads(line[6:]) for line in resp if line.startswith(b"data: ")]
    except (OSError, ValueError) as exc:
        check("Research stream completed", False, str(exc))
        return []


def _cited_answer(events):
    draft = "".join(event["token"] for event in events if event["type"] == "token")
    citations = {
        source["index"]
        for event in events
        if event["type"] == "sources"
        for source in event["sources"]
        if source.get("chunkId")
    }
    markers = {
        int(number)
        for group in re.findall(r"\[([0-9]+(?:,\s*[0-9]+)*)\]", draft)
        for number in group.split(",")
    }
    return draft, markers, citations


def _stream_completed(events):
    types = [event["type"] for event in events]
    return "done" in types and "error" not in types


def check_assistant_research(combo, auth):
    """Require live, distinct streams and a verified answer from the demo library."""
    events = _research_events(
        combo,
        auth,
        query="What warning signs of collusive bidding do the World Bank procurement reports "
        "describe, and how can digital tools help detect fraud in public spending?",
    )
    searches = [
        query
        for event in events
        if event["type"] == "search_status"
        for query in event["queries"]
    ]
    streams = {query["stream"] for query in searches if query.get("stream")}
    check("Assistant runs at least two distinct research streams", len(streams) >= 2)
    draft, markers, citations = _cited_answer(events)
    check(
        "Assistant completes citation checking and returns a grounded answer",
        _stream_completed(events)
        and any(event.get("phase") == "checking_citations" for event in events)
        and bool(draft.strip())
        and bool(markers)
        and markers <= citations,
    )


def check_brief_survey(combo, auth):
    """Require library evidence without answer generation during the outline survey."""
    topic = "Recognising fraud risks in public procurement"
    events = _research_events(
        combo, auth, query=topic, usage_context="brief", brief_survey={"topic": topic}
    )
    check(
        "Brief outline survey gathers evidence without drafting or checking citations",
        _stream_completed(events)
        and any(event["type"] == "sources" and event["sources"] for event in events)
        and not any(
            event["type"] == "token"
            or event.get("phase") in {"synthesizing", "checking_citations"}
            for event in events
        ),
    )


def check_brief_generation(combo, auth):
    """Write two sections of different lengths from the demo library."""
    cases = (
        (
            "Warning signs of collusion in bid submissions",
            150,
            "Describe warning signs in bidding. Leave digital detection to the other section.",
            "Write in plain English for a reader who is new to procurement.",
        ),
        (
            "Digital detection of fraud in public spending",
            250,
            "Describe how digital tools detect and flag fraud. Leave bidding to the other section.",
            "Use a formal audit voice. Use third person and attribute findings to the reports.",
        ),
    )
    outline = [{"title": heading} for heading, *_ in cases]
    for current, (heading, target, focus, voice) in enumerate(cases):
        section = {
            "topic": "Recognising fraud risks in public procurement",
            "outline": outline,
            "current": current,
            "focus": focus,
            "voice_instructions": voice,
        }
        _check_brief_section(combo, auth, heading, target, section)


def _check_brief_section(combo, auth, heading, target, section):
    events = _research_events(
        combo,
        auth,
        query=heading,
        target_words=target,
        usage_context="brief",
        brief_section=section,
    )
    draft, markers, citations = _cited_answer(events)
    words = len(re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", draft).split())
    phases = [event.get("phase") for event in events if event["type"] == "phase"]
    written = any(event.get("section_written") is True for event in events)
    length = eval_brief_length(
        {}, {"written": written, "assignment": {"target_words": target}, "words": words}
    )
    check(
        f"{heading} produced reviewed prose without extra headings",
        _stream_completed(events)
        and written
        and "checking_citations" in phases
        and not re.search(r"(?m)^#{1,6}\s", draft),
        f"phases={phases}, section_written={written}",
    )
    check(f"{heading} meets the Brief word target", length["passed"], length["message"])
    check(f"{heading} cites real sources", bool(markers) and markers == citations)


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
    print("[1/7] API health...")
    status, body = _get(f"{API_URL}/health", headers=auth)
    check("API /health returns 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 2. UI serves
    # ------------------------------------------------------------------
    print("[2/7] UI...")
    status, _ = _get(UI_URL)
    check("UI serves HTTP 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 3. MCP server health
    # ------------------------------------------------------------------
    print("[3/7] MCP server...")
    status, body = _get(f"{MCP_URL}/health")
    check("MCP /health returns 200", status == 200, f"status={status}")
    print()

    # ------------------------------------------------------------------
    # 4. Search returns results
    # ------------------------------------------------------------------
    print("[4/7] Search API...")
    # Search the way the UI does: with the embedding model of the combo the
    # UI starts on for this data source (the flagged default, else the first).
    status, body = _get(
        f"{API_URL}/config/model-combos?data_source={DEMO_DATA_SOURCE}", headers=auth
    )
    check("Model combos returns 200", status == 200, f"status={status}")
    combos = json.loads(body) if status == 200 else {}
    check("Demo data source has a model combo", bool(combos), f"got {combos}")
    starting = next(
        (c for c in combos.values() if c.get("default")),
        next(iter(combos.values()), {}),
    )
    model = starting.get("embedding_model", "")
    status, body = _get(
        f"{API_URL}/search?q=corruption+investigation"
        f"&data_source={DEMO_DATA_SOURCE}&model={model}",
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
    print("[5/7] A2A research task...")
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
                            "text": (
                                "What is one way to detect fraud in public procurement? "
                                "Give one finding in one sentence with a citation."
                            ),
                        }
                    ],
                    "metadata": {"data_source": DEMO_DATA_SOURCE},
                },
            },
        },
        headers=auth,
    )
    detail = body.get("error", "") if status == 0 else ""
    check(
        "A2A tasks/send returns 200", status == 200, f"status={status} {detail}".strip()
    )
    if status == 200:
        result = body.get("result", {})
        state = result.get("status", {}).get("state", "")
        check(
            "A2A research task completed",
            state == "completed",
            f"state={state!r}",
        )
    print()

    print("[6/7] Assistant research...")
    check_assistant_research(starting, auth)
    print()

    print("[7/7] Brief outline and section generation...")
    check_brief_survey(starting, auth)
    check_brief_generation(starting, auth)
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
