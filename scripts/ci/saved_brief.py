"""A realistic saved brief, built through the API exactly as the web app builds one.

The layout test (tests/integration/test_ui_layout.py) and the UX review in CI
open a saved brief: headings and sub-headings, cited sources with long titles,
lists, a long unbroken address, and one citation that resolved to no source
(shown as a red ``?n`` badge).

A brief kept by a signed-out browser lives in localStorage, in the form the API
stores it. This builds that form through ``POST /brief/citations``: the
structure first, then one run per section, the same operations the Brief tab
sends. The caller puts the result in localStorage under ``BRIEF_HISTORY_KEY``
(see ``local_storage_script``), opens the Brief tab, chooses "Load a saved
brief" and then ``BRIEF_TITLE``. (A ``/brief/<id>`` link opens only a signed-in
brief.)

Usage, in the pipeline container (API key from API_SECRET_KEY):
  python -m scripts.ci.saved_brief --api-url http://api:8000 --out saved-brief.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

BRIEF_ID = "ux-review-saved-brief"
BRIEF_TITLE = "School meals: what the evaluations show"
BRIEF_HISTORY_KEY = "evidencelab_brief_history_v1"
# The stored citation format the API accepts (BRIEF_CITATIONS_VERSION in the
# web app). The API refuses any other, so a change there fails this loudly.
CITATIONS_VERSION = 2

Poster = Callable[[dict[str, Any]], dict[str, Any]]

_REPORT = (
    "Evaluation of the National School Feeding Programme in Kenya and Lesotho, "
    "2019-2023: Final Report and Annexes"
)

# The sources the sections cite, as the research agent returns them.
SOURCES: dict[str, dict[str, Any]] = {
    "meals": {
        "chunkId": "ux-chunk-meals",
        "docId": "ux-doc-1",
        "title": _REPORT,
        "text": "Attendance rose by 9 percentage points in schools serving a daily "
        "hot meal, with the largest gains among girls aged 10 to 14.",
        "score": 0.91,
        "page": 42,
        "headings": ["4 Findings", "4.2 Attendance and enrolment"],
    },
    "nutrition": {
        "chunkId": "ux-chunk-nutrition",
        "docId": "ux-doc-1",
        "title": _REPORT,
        "text": "Anaemia prevalence among pupils fell from 31% to 24% where meals "
        "used fortified flour and locally sourced pulses.",
        "score": 0.88,
        "page": 57,
        "headings": ["4 Findings", "4.3 Nutrition"],
    },
    "cost": {
        "chunkId": "ux-chunk-cost",
        "docId": "ux-doc-2",
        "title": "Home-Grown School Feeding: Cost-Effectiveness Review of Twelve Country "
        "Programmes (Synthesis Report)",
        "text": "The cost per child per year ranged from US$28 to US$61, and local "
        "procurement lowered it by about a fifth in four of the twelve countries.",
        "score": 0.84,
        "page": 13,
        "headings": ["Executive summary"],
    },
    "governance": {
        "chunkId": "ux-chunk-governance",
        "docId": "ux-doc-3",
        "title": "Strategic Evaluation of Government Ownership and Transition of School "
        "Meals Programmes",
        "text": "Transition to national ownership was slowest where budget lines for "
        "school meals were not protected in the annual appropriation.",
        "score": 0.8,
        "page": 88,
        "headings": ["Conclusions", "Transition"],
    },
}

_LONG_ADDRESS = (
    "https://evaluation.example.org/reports/school-feeding/"
    "annex-b-detailed-cost-effectiveness-tables-by-country-and-year-2019-2023"
)

# Each section's text uses the agent's own numbers, which match the `index`
# of the sources listed with it. [9] in "Cost and sustainability" matches none,
# so the API records it as unresolved.
SECTIONS: list[dict[str, Any]] = [
    {
        "id": "ux-overview",
        "title": "Overview",
        "level": 1,
        "content": "School meals raised attendance and improved nutrition in both "
        "countries [1][2], at a cost that varied widely between programmes [3].",
        "sources": ["meals", "nutrition", "cost"],
    },
    {
        "id": "ux-findings",
        "title": "Findings",
        "level": 1,
        "content": "The evidence comes from two country evaluations and one synthesis "
        "of twelve programmes [1][2].",
        "sources": ["meals", "cost"],
    },
    {
        "id": "ux-attendance",
        "title": "Attendance and nutrition",
        "level": 2,
        "content": "Daily hot meals had the clearest effect on attendance [1]:\n\n"
        "- attendance rose by 9 percentage points [1];\n"
        "- the largest gains were among girls aged 10 to 14 [1];\n"
        "- anaemia fell from 31% to 24% where flour was fortified [2].\n\n"
        f"The country tables are in Annex B: {_LONG_ADDRESS}",
        "sources": ["meals", "nutrition"],
    },
    {
        "id": "ux-cost",
        "title": "Cost and sustainability",
        "level": 2,
        "content": "Costs ranged from US$28 to US$61 per child per year [1], and "
        "buying food locally lowered them by about a fifth in four countries [1]. "
        "Programmes that kept a protected budget line moved to national ownership "
        "faster [2][9].",
        "sources": ["cost", "governance"],
    },
    {
        "id": "ux-recommendations",
        "title": "Recommendations",
        "level": 1,
        "content": "1. Protect a budget line for school meals in each annual "
        "appropriation [1].\n"
        "2. Buy food locally where markets allow, to lower the cost per child [2].\n"
        "3. Fortify flour wherever anaemia among pupils is above 20% [3].",
        "sources": ["governance", "cost", "nutrition"],
    },
]


def brief_structure(now_ms: int) -> dict[str, Any]:
    """The brief as the Brief tab saves it: structure and settings, no citations."""
    return {
        "id": BRIEF_ID,
        "title": BRIEF_TITLE,
        "query": "What do evaluations say about the effects and costs of school meals?",
        "date": now_ms,
        "sectionCount": len(SECTIONS),
        "sourceCount": len(SOURCES),
        "citationsVersion": CITATIONS_VERSION,
        "referenceGrouping": "passage",
        "sections": [
            {"id": s["id"], "title": s["title"], "level": s["level"], "status": "done"}
            for s in SECTIONS
        ],
    }


def run_body(section: dict[str, Any]) -> dict[str, Any]:
    """A section's research run, as the Brief tab records it."""
    sources = [
        {**SOURCES[key], "index": number}
        for number, key in enumerate(section["sources"], start=1)
    ]
    return {
        "mode": "generate",
        "content": section["content"],
        "sources": sources,
        "based_on": None,
        "run_id": None,
        "question": None,
        "instruction": None,
        "note": None,
        "review": False,
    }


def build_saved_brief(post: Poster, now_ms: Optional[int] = None) -> dict[str, Any]:
    """The stored form of the saved brief, built with POST."""
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    content: dict[str, Any] = {
        "citationsVersion": CITATIONS_VERSION,
        "referenceGrouping": "passage",
        "sources": [],
        "sections": [],
    }
    content = post(
        {"content": content, "op": {"type": "structure", "brief": brief_structure(now)}}
    )["content"]
    for section in SECTIONS:
        op = {"type": "run", "sectionId": section["id"], "run": run_body(section)}
        content = post({"content": content, "op": op})["content"]
    return content


def api_poster(api_url: str, api_key: str) -> Poster:
    """POST to the API's /brief/citations; raise on any error status."""

    def post(body: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{api_url.rstrip('/')}/brief/citations",
            json=body,
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    return post


def local_storage_script(content: dict[str, Any]) -> str:
    """JavaScript that puts CONTENT in the browser as its only saved brief."""
    return (
        f"localStorage.setItem({json.dumps(BRIEF_HISTORY_KEY)}, "
        f"{json.dumps(json.dumps([content]))});"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    content = build_saved_brief(api_poster(args.api_url, os.environ["API_SECRET_KEY"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(content))
    print(f"Saved brief {BRIEF_ID} written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
