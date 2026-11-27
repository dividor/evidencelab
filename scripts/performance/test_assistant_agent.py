"""Measure search progress and completion through the Assistant service."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


def describe(event, show_answer):
    kind = event["type"]
    if kind == "phase":
        return event["phase"]
    if kind == "search_status":
        return "\n".join(
            f'{query["query"]} ({query["result_count"]} results)'
            for query in event["queries"]
        )
    if kind == "token":
        return (
            event["token"]
            if show_answer
            else f'Answer ({len(event["token"].split())} words)'
        )
    if kind == "done":
        return f'Completed. Model usage: {event.get("usage", {})}'
    return ""


async def measure(args):
    from ui.backend.services.assistant_service import stream_research_response

    started = time.monotonic()
    async for event in stream_research_response(
        query=args.query,
        data_source=args.data_source,
        model_key=args.model,
        reranker_model=None if args.no_rerank else args.reranker,
        deep_research=args.deep_research,
    ):
        if event["type"] == "error":
            raise RuntimeError(event["error"])
        description = (
            json.dumps(event, default=str)
            if args.events
            else describe(event, args.stream_tokens)
        )
        if description:
            print(f"[{time.monotonic() - started:6.1f}s] {description}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", "-q", default="What are the key findings on food security?"
    )
    parser.add_argument("--model", "-m")
    parser.add_argument("--data-source", "-d")
    parser.add_argument("--reranker", "-r")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--deep-research", action="store_true")
    parser.add_argument(
        "--stream-tokens", action="store_true", help="Print the final answer"
    )
    parser.add_argument(
        "--events", action="store_true", help="Print the raw Assistant events"
    )
    asyncio.run(measure(parser.parse_args()))


if __name__ == "__main__":
    main()
