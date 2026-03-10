"""
Performance test for the Research Assistant agent.

Calls the agent directly (same code path as the UI) and logs detailed
timing for every graph step — LLM calls, tool calls, and phase transitions.

Usage:
  # Run inside the API container (has all dependencies):
  docker compose exec api python scripts/performance/test_assistant_agent.py

  # With a specific query:
  docker compose exec api python scripts/performance/test_assistant_agent.py \
      --query "What are the key findings on food security?"

  # With a specific model:
  docker compose exec api python scripts/performance/test_assistant_agent.py \
      --model gpt-4.1-mini

  # Token-level streaming (shows tokens as they arrive):
  docker compose exec api python scripts/performance/test_assistant_agent.py \
      --stream-tokens

  # Use astream_events for fine-grained event logging:
  docker compose exec api python scripts/performance/test_assistant_agent.py \
      --events
"""

import argparse
import asyncio
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


# ── Colours for terminal output ──────────────────────────────────────────
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"


def ts():
    """Elapsed time since start, formatted."""
    return f"{time.time() - _t0:6.1f}s"


_t0 = 0.0

DEFAULT_QUERY = "What are the key findings on food security?"
DEFAULT_DATA_SOURCE = None  # uses whatever is configured


def get_llm(model_key=None):
    from utils.llm_factory import get_llm as factory_get_llm

    return factory_get_llm(model=model_key, temperature=0.2, max_tokens=2000)


def build_agent(llm, data_source=None):
    from ui.backend.services.assistant_graph import build_research_agent

    return build_research_agent(llm, data_source)


# ── Mode 1: step-level streaming (same as UI) ───────────────────────────
async def run_updates_mode(agent, tracker, query, data_source):
    """Stream with stream_mode='updates' — same as the UI code path."""
    from langchain_core.messages import HumanMessage

    print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
    print(f"{C.BOLD}  Mode: updates (same as UI){C.RESET}")
    print(f"{C.BOLD}{'═' * 70}{C.RESET}\n")

    messages = [HumanMessage(content=query)]
    step_num = 0
    search_count = 0
    llm_call_count = 0

    step_start = time.time()

    async for step_output in agent.astream(
        {"messages": messages},
        config={"recursion_limit": 12},
        stream_mode="updates",
    ):
        elapsed = time.time() - step_start
        step_num += 1

        for node_name, node_output in step_output.items():
            if node_name == "model":
                llm_call_count += 1
                msgs = node_output.get("messages", [])
                for msg in msgs:
                    tool_calls = getattr(msg, "tool_calls", None)
                    if tool_calls:
                        queries = [
                            tc.get("args", {}).get("query", "?")
                            for tc in tool_calls
                            if tc.get("name") == "search_documents"
                        ]
                        other_tools = [
                            tc.get("name")
                            for tc in tool_calls
                            if tc.get("name") != "search_documents"
                        ]
                        if queries:
                            for q in queries:
                                print(
                                    f"  {C.CYAN}[{ts()}]{C.RESET} "
                                    f"{C.YELLOW}LLM → search{C.RESET} "
                                    f"({elapsed:.1f}s) "
                                    f'"{q}"'
                                )
                        if other_tools:
                            print(
                                f"  {C.CYAN}[{ts()}]{C.RESET} "
                                f"{C.MAGENTA}LLM → tools{C.RESET} "
                                f"({elapsed:.1f}s) "
                                f"{other_tools}"
                            )
                    elif hasattr(msg, "content") and msg.content:
                        text = msg.content
                        preview = text[:120].replace("\n", " ")
                        print(
                            f"  {C.CYAN}[{ts()}]{C.RESET} "
                            f"{C.GREEN}LLM → response{C.RESET} "
                            f"({elapsed:.1f}s) "
                            f"{len(text)} chars: "
                            f'"{preview}..."'
                        )

            elif node_name == "tools":
                msgs = node_output.get("messages", [])
                for msg in msgs:
                    content = getattr(msg, "content", "")
                    search_count += 1
                    result_count = content.count("---") if "---" in content else 0
                    is_limit = "SEARCH LIMIT" in content
                    if is_limit:
                        print(
                            f"  {C.CYAN}[{ts()}]{C.RESET} "
                            f"{C.RED}SEARCH LIMIT HIT{C.RESET} "
                            f"({elapsed:.1f}s)"
                        )
                    else:
                        print(
                            f"  {C.CYAN}[{ts()}]{C.RESET} "
                            f"  Search complete "
                            f"({elapsed:.1f}s) "
                            f"→ ~{result_count} results"
                        )

            else:
                print(
                    f"  {C.CYAN}[{ts()}]{C.RESET} "
                    f"{C.DIM}[{node_name}]{C.RESET} "
                    f"({elapsed:.1f}s)"
                )

        step_start = time.time()

    total = time.time() - _t0
    print(f"\n{C.BOLD}{'─' * 70}{C.RESET}")
    print(f"  {C.BOLD}Total: {total:.1f}s{C.RESET}")
    print(f"  LLM calls: {llm_call_count}")
    print(f"  Search calls: {search_count}")
    print(f"  Tracker queries: {len(tracker.per_query)}")
    print(f"  Total results: {len(tracker.all_results)}")
    print(f"{C.BOLD}{'─' * 70}{C.RESET}\n")


# ── Mode 2: token-level streaming ────────────────────────────────────────
async def run_messages_mode(agent, tracker, query, data_source):
    """Stream with stream_mode=['updates', 'messages'] for token-level output."""
    from langchain_core.messages import HumanMessage

    print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
    print(f"{C.BOLD}  Mode: updates + messages (token-level){C.RESET}")
    print(f"{C.BOLD}{'═' * 70}{C.RESET}\n")

    messages = [HumanMessage(content=query)]
    token_count = 0
    first_token_time = None
    step_start = time.time()

    async for chunk in agent.astream(
        {"messages": messages},
        config={"recursion_limit": 12},
        stream_mode=["updates", "messages"],
    ):
        mode = chunk[0] if isinstance(chunk, tuple) else "updates"
        data = chunk[1] if isinstance(chunk, tuple) else chunk

        if mode == "messages":
            # data is (AIMessageChunk, metadata)
            msg_chunk, metadata = data
            text = getattr(msg_chunk, "content", "")
            tool_calls = getattr(msg_chunk, "tool_call_chunks", [])

            if text:
                token_count += 1
                if first_token_time is None:
                    first_token_time = time.time()
                    print(
                        f"  {C.CYAN}[{ts()}]{C.RESET} "
                        f"{C.GREEN}First token{C.RESET} "
                        f"(TTFT: {first_token_time - _t0:.1f}s)"
                    )
                sys.stdout.write(text)
                sys.stdout.flush()

            if tool_calls:
                for tc in tool_calls:
                    name = (
                        tc.get("name")
                        if isinstance(tc, dict)
                        else getattr(tc, "name", None)
                    )
                    if name:
                        print(
                            f"\n  {C.CYAN}[{ts()}]{C.RESET} "
                            f"{C.YELLOW}Tool call: {name}{C.RESET}"
                        )

        elif mode == "updates":
            elapsed = time.time() - step_start
            for node_name, node_output in data.items():
                if node_name == "tools":
                    new_queries = tracker.get_new_queries()
                    for q_info in new_queries:
                        print(
                            f"\n  {C.CYAN}[{ts()}]{C.RESET} "
                            f"  Search: \"{q_info['query']}\" "
                            f"→ {q_info['result_count']} results "
                            f"({elapsed:.1f}s)"
                        )
                    if first_token_time is not None:
                        # Reset for next response chunk
                        first_token_time = None
                        token_count = 0
                elif node_name == "model":
                    pass  # messages mode handles this
                else:
                    print(
                        f"\n  {C.CYAN}[{ts()}]{C.RESET} "
                        f"{C.DIM}[{node_name}]{C.RESET}"
                    )
            step_start = time.time()

    total = time.time() - _t0
    print(f"\n\n{C.BOLD}{'─' * 70}{C.RESET}")
    print(f"  {C.BOLD}Total: {total:.1f}s{C.RESET}")
    print(f"  Tracker queries: {len(tracker.per_query)}")
    print(f"  Total results: {len(tracker.all_results)}")
    print(f"{C.BOLD}{'─' * 70}{C.RESET}\n")


# ── Mode 3: astream_events for fine-grained event logging ────────────────
async def run_events_mode(agent, tracker, query, data_source):
    """Use astream_events v2 for the most detailed timing."""
    from langchain_core.messages import HumanMessage

    print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
    print(f"{C.BOLD}  Mode: astream_events (fine-grained){C.RESET}")
    print(f"{C.BOLD}{'═' * 70}{C.RESET}\n")

    messages = [HumanMessage(content=query)]
    seen_events = set()

    async for event in agent.astream_events(
        {"messages": messages},
        config={"recursion_limit": 12},
        version="v2",
    ):
        kind = event.get("event", "")
        name = event.get("name", "")
        run_id = str(event.get("run_id", ""))[:8]

        # Filter to interesting events
        if kind == "on_chat_model_start":
            print(
                f"  {C.CYAN}[{ts()}]{C.RESET} "
                f"{C.YELLOW}LLM start{C.RESET} "
                f"({name})"
            )
        elif kind == "on_chat_model_end":
            output = event.get("data", {}).get("output", {})
            msg = output if hasattr(output, "tool_calls") else None
            tool_calls = getattr(msg, "tool_calls", []) if msg else []
            content = getattr(msg, "content", "") if msg else ""
            tc_str = ""
            if tool_calls:
                tc_names = [tc.get("name", "?") for tc in tool_calls]
                tc_str = f" → tools: {tc_names}"
            elif content:
                tc_str = f" → response ({len(content)} chars)"
            print(
                f"  {C.CYAN}[{ts()}]{C.RESET} "
                f"{C.YELLOW}LLM end{C.RESET} "
                f"({name}){tc_str}"
            )
        elif kind == "on_tool_start":
            data = event.get("data", {})
            tool_input = data.get("input", {})
            q = tool_input.get("query", "?") if isinstance(tool_input, dict) else "?"
            print(
                f"  {C.CYAN}[{ts()}]{C.RESET} "
                f"{C.MAGENTA}Tool start{C.RESET} "
                f'({name}) query="{q}"'
            )
        elif kind == "on_tool_end":
            data = event.get("data", {})
            output = data.get("output", "")
            out_str = str(output)
            is_limit = "SEARCH LIMIT" in out_str
            result_count = out_str.count("---") if not is_limit else 0
            if is_limit:
                print(
                    f"  {C.CYAN}[{ts()}]{C.RESET} "
                    f"{C.RED}Tool end: SEARCH LIMIT HIT{C.RESET}"
                )
            else:
                print(
                    f"  {C.CYAN}[{ts()}]{C.RESET} "
                    f"{C.MAGENTA}Tool end{C.RESET} "
                    f"({name}) → ~{result_count} results"
                )
        elif kind == "on_chat_model_stream":
            # Skip token events for cleaner output
            key = f"{kind}:{run_id}"
            if key not in seen_events:
                seen_events.add(key)
                print(
                    f"  {C.CYAN}[{ts()}]{C.RESET} " f"{C.DIM}LLM streaming...{C.RESET}"
                )

    total = time.time() - _t0
    print(f"\n{C.BOLD}{'─' * 70}{C.RESET}")
    print(f"  {C.BOLD}Total: {total:.1f}s{C.RESET}")
    print(f"  Tracker queries: {len(tracker.per_query)}")
    print(f"  Total results: {len(tracker.all_results)}")
    print(f"{C.BOLD}{'─' * 70}{C.RESET}\n")


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    global _t0

    parser = argparse.ArgumentParser(
        description="Test Research Assistant agent performance"
    )
    parser.add_argument("--query", "-q", default=DEFAULT_QUERY, help="Query to test")
    parser.add_argument(
        "--model", "-m", default=None, help="Model key (e.g. gpt-4.1-mini)"
    )
    parser.add_argument(
        "--data-source",
        "-d",
        default=DEFAULT_DATA_SOURCE,
        help="Data source to search",
    )
    parser.add_argument(
        "--stream-tokens",
        action="store_true",
        help="Use messages mode for token-level streaming",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Use astream_events for fine-grained event logging",
    )
    args = parser.parse_args()

    print(f"\n{C.BOLD}Research Assistant Performance Test{C.RESET}")
    print(f"{'─' * 70}")
    print(f"  Query:       {args.query}")
    print(f"  Model:       {args.model or '(default from config)'}")
    print(f"  Data source: {args.data_source or '(all)'}")
    print("  Max searches: 4 (hard limit)")
    print("  Recursion:   12")
    print(f"{'─' * 70}")

    # Build LLM and agent
    print("\n  Building agent...", end=" ", flush=True)
    llm = get_llm(args.model)
    agent, tracker = build_agent(llm, args.data_source)
    print(f"done ({type(llm).__name__})")

    _t0 = time.time()

    if args.events:
        asyncio.run(run_events_mode(agent, tracker, args.query, args.data_source))
    elif args.stream_tokens:
        asyncio.run(run_messages_mode(agent, tracker, args.query, args.data_source))
    else:
        asyncio.run(run_updates_mode(agent, tracker, args.query, args.data_source))


if __name__ == "__main__":
    main()
