#!/usr/bin/env python3
"""
Log Analysis Script
Parses orchestrator logs to generate a timeline of events for each document.
"""

import argparse
import glob
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, NamedTuple, Optional

# Log format:
# 2026-01-01 22:25:07,270 - [SpawnProcess-3:56439:0a208f5a-0306-5603-bfb6-46a0c2447e8f] - INFO - ...
LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - \[(.*?):(\d+):(.*?)] - (\w+) - (.*)$"
)


class LogEvent(NamedTuple):
    timestamp: str
    process: str
    pid: str
    level: str
    message: str


def parse_logs(
    inputs: List[str] = None, file_id: Optional[str] = None
) -> Dict[str, List[LogEvent]]:
    """Parse logs and group by doc_id. Inputs can be files or directories.

    Args:
        inputs: List of log files or directories to parse
        file_id: Optional file ID to filter logs for a specific document

    Returns:
        Dictionary mapping doc_id to list of LogEvent objects
    """
    if not inputs:
        inputs = ["logs"]

    files_to_parse = []

    for inp in inputs:
        if os.path.isdir(inp):
            # If directory, only use current orchestrator.log (not rotated files)
            orchestrator_log = os.path.join(inp, "orchestrator.log")
            if os.path.exists(orchestrator_log):
                files_to_parse.append(orchestrator_log)
            else:
                # Try just all .log files if orchestrator.log doesn't exist
                found = glob.glob(f"{inp}/*.log")
                files_to_parse.extend(found)
        elif os.path.isfile(inp):
            files_to_parse.append(inp)
        else:
            # Try globbing just in case string was passed with wildcard but quoted
            found = glob.glob(inp)
            if found:
                files_to_parse.extend(found)
            else:
                print(
                    f"Warning: {inp} is not a valid file or directory", file=sys.stderr
                )

    events_by_doc = defaultdict(list)

    # Dedup files
    files_to_parse = sorted(list(set(files_to_parse)))

    if file_id:
        print("Filtering logs for file-id: " + str(file_id), file=sys.stderr)
        if not files_to_parse:
            print(f"Warning: No log files found in inputs: {inputs}", file=sys.stderr)
    else:
        print(f"Found {len(files_to_parse)} log files to parse...")

    matched_count = 0
    for log_file in files_to_parse:
        if not file_id:
            print(f"Parsing {log_file}...")
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    match = LOG_PATTERN.match(line)
                    if match:
                        timestamp, process, pid, doc_id, level, message = match.groups()

                        # Filter out N/A doc IDs
                        if doc_id == "N/A":
                            continue

                        # If file_id is specified, only include events for that document
                        # Handle both string and integer comparisons (logs might have either format)
                        if file_id:
                            # Try exact match first
                            if doc_id != file_id:
                                # Try converting both to int for comparison
                                try:
                                    if int(doc_id) != int(file_id):
                                        continue
                                except (ValueError, TypeError):
                                    # If conversion fails, they don't match
                                    continue

                            matched_count += 1

                        event = LogEvent(
                            timestamp, process, pid, level, message.strip()
                        )
                        events_by_doc[doc_id].append(event)
        except Exception as e:
            print(f"Error reading {log_file}: {e}", file=sys.stderr)

    if file_id:
        print(
            f"Found {matched_count} matching log lines for file-id: {file_id}",
            file=sys.stderr,
        )
        print(f"Total unique doc_ids in result: {len(events_by_doc)}", file=sys.stderr)

    return events_by_doc


def print_timelines(events_by_doc: Dict[str, List[LogEvent]]):
    """Print timeline for each document."""
    print(f"\nFound {len(events_by_doc)} unique documents.\n")

    # Sort documents by first event timestamp
    sorted_docs = sorted(
        events_by_doc.items(),
        key=lambda item: sorted(item[1], key=lambda e: e.timestamp)[0].timestamp,
    )

    for doc_id, events in sorted_docs:
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        start_time = sorted_events[0].timestamp
        end_time = sorted_events[-1].timestamp

        print("=" * 100)
        print(f"📄 Document ID: {doc_id}")
        print(f"   First Event: {start_time}")
        print(f"   Last Event:  {end_time}")
        print(f"   Events:      {len(sorted_events)}")
        print("-" * 100)

        for e in sorted_events:
            print(f"{e.timestamp} | {e.process:20} | {e.level:5} | {e.message}")

        print("\n")


def save_logs_to_file(events: List[LogEvent], output_path: str):
    """Save log events to a file in a readable format. Overwrites existing file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Use 'w' mode to overwrite existing file (not append)
    with open(output_path, "w", encoding="utf-8") as f:
        # Write header
        f.write("=" * 100 + "\n")
        f.write("Processing Logs\n")
        f.write(f"Total Events: {len(events)}\n")
        if events:
            f.write(f"First Event: {events[0].timestamp}\n")
            f.write(f"Last Event:  {events[-1].timestamp}\n")
        f.write("=" * 100 + "\n\n")

        # Write events
        for e in events:
            f.write(f"{e.timestamp} | {e.process:20} | {e.level:5} | {e.message}\n")

    print(f"Saved {len(events)} log events to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse orchestrator logs to generate a timeline of events for documents."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["logs"],
        help="Log files or directories to parse (default: logs)",
    )
    parser.add_argument(
        "--file-id",
        type=str,
        help="Filter logs for a specific file ID",
    )
    parser.add_argument(
        "--parsed-folder",
        type=str,
        help="Path to parsed folder where processing.log should be saved (requires --file-id)",
    )

    args = parser.parse_args()

    # If parsed_folder is provided, file_id must also be provided
    if args.parsed_folder and not args.file_id:
        print("Error: --parsed-folder requires --file-id", file=sys.stderr)
        sys.exit(1)

    data = parse_logs(args.inputs, file_id=args.file_id)

    # If file_id and parsed_folder are provided, save logs to processing.log
    if args.file_id and args.parsed_folder:
        # Check if we found logs - handle both string and int key formats
        found_events = None
        if args.file_id in data:
            found_events = data[args.file_id]
        else:
            # Try integer version (convert to string for dict lookup)
            try:
                int_file_id = int(args.file_id)
                str_file_id = str(int_file_id)
                if str_file_id in data:
                    found_events = data[str_file_id]
            except (ValueError, TypeError):
                pass

        if found_events:
            events = sorted(found_events, key=lambda e: e.timestamp)
            output_path = os.path.join(args.parsed_folder, "processing.log")
            save_logs_to_file(events, output_path)
        else:
            print(
                f"Warning: No logs found for file-id: {args.file_id}", file=sys.stderr
            )
            # Create empty file to indicate no logs found
            output_path = os.path.join(args.parsed_folder, "processing.log")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("No processing logs found for this document.\n")
    else:
        # Default behavior: print timelines
        print_timelines(data)
