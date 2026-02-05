#!/usr/bin/env python3
"""
Script to test TOC classification on a single file.
Takes a file-id, extracts the current TOC, prints it,
then predicts the TOC using SectionTypeTagger and prints that.

Usage:
    python3 tests/evaluation/toc_classification/predict_one_toc_all.py --file-id <file_id>
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, Union

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))  # noqa: E402

from pipeline.db import Database, load_datasources_config  # noqa: E402
from pipeline.processors.parsing.parser import ParseProcessor  # noqa: E402
from pipeline.processors.tagging.tagger import TaggerProcessor  # noqa: E402


def format_toc_output(item: Union[str, Dict[str, Any]], label: str = None) -> str:
    """
    Format a TOC item for display.
    Target format: "{Category:<25} {Indent}[H{Level}] {Title} | page {Page}"

    Args:
        item: Either a raw TOC line string (from DB) or an entry dict (from Tagger)
        label: The classification label (only used if item is a dict)
    """
    category_width = 25

    # CASE 1: parsing a raw string from DB
    # Expected format: "   [H2] Title | category | page 123"
    if isinstance(item, str):
        line = item.strip()
        # Regex to parse: [indent][Hx] title | category (| page X)?
        # Note: formatting might put category at end.
        pattern = (
            r"^(?P<indent>\s*)\[H(?P<level>\d+)\]\s*(?P<title>.*?)\s*\|\s*"
            r"(?P<category>[^|]+)(?:\s*\|\s*page\s*(?P<page>\d+)"
            r"(?:\s*\((?P<roman>[^)]+)\))?)?$"
        )
        match = re.search(pattern, line)

        if match:
            level = int(match.group("level"))
            title = match.group("title").strip()
            category = match.group("category").strip()
            page = match.group("page")
            roman = match.group("roman")

            indent_spaces = "  " * (level - 1)
            roman_str = f" ({roman})" if roman else ""
            page_str = f" | page {page}{roman_str}" if page else ""

            return f"{category:<{category_width}} {indent_spaces}[H{level}] {title}{page_str}"
        else:
            # Fallback for unrecognizable lines
            return line

    # CASE 2: formatting a dict entry from Tagger
    elif isinstance(item, dict):
        entry = item
        level = entry.get("level", 1)
        title = entry.get("title", "").strip()
        page = entry.get("page")
        category = label if label else "other"

        indent_spaces = "  " * (level - 1)
        page_str = f" | page {page}" if page is not None else ""

        return (
            f"{category:<{category_width}} {indent_spaces}[H{level}] {title}{page_str}"
        )

    return str(item)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Test TOC classification on one file")
    parser.add_argument(
        "--file-id", required=True, help="The Qdrant Point ID of the file"
    )
    parser.add_argument(
        "--data-source", default="uneg", help="Data source suffix (default: uneg)"
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="Reparse the document and use generated TOC for prediction",
    )

    args = parser.parse_args()

    try:
        # 1. Connect to DB
        logger.info(f"Connecting to Database (source={args.data_source})...")
        db = Database(data_source=args.data_source)
        collection_name = db.documents_collection

        # 2. Get Document
        logger.info(f"Fetching document {args.file_id}...")
        points = db.client.retrieve(
            collection_name=collection_name, ids=[args.file_id], with_payload=True
        )

        if not points:
            logger.error(f"Document {args.file_id} not found in {collection_name}")
            return

        point = points[0]
        payload = point.payload

        doc_title = payload.get("title") or payload.get("map_title") or "Unknown Title"
        current_toc = payload.get("sys_toc", "")
        current_classified = payload.get("sys_toc_classified", "")
        filepath = (
            payload.get("filepath")
            or payload.get("sys_filepath")
            or payload.get("file_path")
            or payload.get("sys_file_path")
            or ""
        )

        logger.info(f"Document Found: {doc_title}")

        # 3. Handle --reparse logic
        if args.reparse:
            if not filepath:
                logger.error("Cannot reparse: No 'filepath' in document payload.")
                return

            print("\n" + "=" * 80)
            print("REPARSING DOCUMENT...")
            print("=" * 80)

            try:
                # Initialize parser
                print("  Initializing Parser (loading models)...")
                import os

                base_data_dir = os.getenv("DATA_MOUNT_PATH", "./data")
                data_dir = f"{base_data_dir}/{args.data_source}"
                parsed_dir = f"{data_dir}/parsed"

                parser_processor = ParseProcessor(output_dir=parsed_dir)
                parser_processor.setup()

                doc_to_parse = {
                    "sys_filepath": filepath,
                    "map_title": doc_title,
                    "id": args.file_id,
                }

                print(f"  Parsing document: {filepath}")
                result = parser_processor.process_document(doc_to_parse)

                if result["success"]:
                    print("  ✓ Parsing successful")

                    updates = result.get("updates", {})
                    parsed_folder = (
                        updates.get("parsed_folder")
                        or updates.get("sys_parsed_folder")
                        or ""
                    )

                    # Save parsed TOC to database
                    parsed_toc = updates.get("toc") or updates.get("sys_toc", "")
                    if parsed_toc:
                        try:
                            point_id = (
                                int(args.file_id)
                                if str(args.file_id).isdigit()
                                else args.file_id
                            )
                            db.client.set_payload(
                                collection_name=collection_name,
                                payload={
                                    "toc": parsed_toc,
                                    "sys_toc": parsed_toc,
                                },
                                points=[point_id],
                            )
                            print("  ✓ Saved parsed TOC to database")
                        except Exception as e:
                            logger.warning(f"  ⚠ Failed to save TOC to database: {e}")

                    toc_path = Path(parsed_folder) / "toc.txt"
                    if not toc_path.exists():
                        toc_path = Path(".") / parsed_folder / "toc.txt"
                    if not toc_path.exists():
                        base_data_dir = os.getenv("DATA_MOUNT_PATH", "./data")
                        toc_path = Path(base_data_dir) / parsed_folder / "toc.txt"

                    if toc_path.exists():
                        print(f"  Reading toc.txt from: {toc_path}")
                        with open(toc_path, "r", encoding="utf-8") as f:
                            toc_content = f.read()

                        # Normalize and format TOC lines
                        normalized_lines = []
                        print("\n" + "=" * 80)
                        print("GENERATED TOC (USED FOR PREDICTION)")
                        print(f"{'CATEGORY':<25} ENTRY")
                        print("=" * 80)

                        if toc_content:
                            for line in toc_content.split("\n"):
                                if not line.strip():
                                    continue

                                # Handle "Page X [H1] Title" format (Page on left)
                                # Regex: optional "page" + digits + space + [H...]
                                match = re.match(
                                    r"^\s*(?:page\s+)?(?P<page>\d+)\s+(?P<rest>\[H\d+\].*)",
                                    line,
                                    re.IGNORECASE,
                                )
                                if match:
                                    # Move page to right: "   [H1] Title | page X"
                                    # Use same indent? Assume indent was minimal if page was first
                                    # Actually, if page is first, indent is before page.
                                    # Let's reconstruct standard format: "[H...] ... | page X"
                                    # But preserve header indent structure if possible?
                                    # Usually "[H1]" implies level.
                                    page = match.group("page")
                                    rest = match.group("rest").strip()
                                    new_line = f"{rest} | page {page}"
                                    normalized_lines.append(new_line)
                                    print(format_toc_output(new_line))
                                else:
                                    # Assume standard format or just text
                                    normalized_lines.append(line)
                                    print(format_toc_output(line))

                            current_toc = "\n".join(normalized_lines)
                        else:
                            print("(Empty TOC file)")
                            current_toc = ""
                        print("=" * 80 + "\n")

                    else:
                        print(f"  ⚠ toc.txt not found at {toc_path}. Using DB TOC.")
                        if parsed_toc:
                            current_toc = parsed_toc

                else:
                    print(f"  ✗ Parsing failed: {result.get('error')}")
                    return

            except Exception as e:
                logger.error(f"  Error running parser: {e}")
                import traceback

                traceback.print_exc()
                return

        else:
            # Not reparsing, print current DB TOC
            print("\n" + "=" * 80)
            print("CURRENT TOC (FROM DB)")
            print(f"{'CATEGORY':<25} ENTRY")
            print("=" * 80)
            if current_classified:
                for line in current_classified.split("\n"):
                    if line.strip():
                        print(format_toc_output(line))
            elif current_toc:
                for line in current_toc.split("\n"):
                    if line.strip():
                        print(format_toc_output(line))
            else:
                print("(No existing TOC found)")
            print("=" * 80 + "\n")

        # 4. Load tag config from datasource config
        full_config = load_datasources_config()
        datasources = full_config.get("datasources", full_config)
        tag_config = {}

        # Find the datasource config
        for key, val in datasources.items():
            if val.get("data_subdir") == args.data_source or key == args.data_source:
                pipeline_config = val.get("pipeline", {})
                tag_config = pipeline_config.get("tag", {})
                break

        if not tag_config:
            logger.warning(
                f"No tag config found for data source '{args.data_source}', using defaults"
            )

        # 5. Predict TOC using TaggerProcessor (same code path as orchestrator)
        print("Running Prediction...")

        # Prepare doc object for tagger
        doc = {
            "id": args.file_id,
            "map_title": doc_title,
            "sys_toc": current_toc,
            "sys_page_count": payload.get("page_count")
            or payload.get("sys_page_count"),
            "sys_filepath": payload.get("sys_filepath")
            or payload.get("filepath")
            or payload.get("file_path")
            or payload.get("sys_file_path"),
        }

        # Run classification
        if current_toc:
            try:
                # Use TaggerProcessor to match orchestrator code path exactly
                tagger_processor = TaggerProcessor(
                    data_source=args.data_source, config=tag_config
                )
                tagger_processor.setup()

                if args.reparse:
                    # Use classify_toc_only which is what the orchestrator uses (saves to DB)
                    result = tagger_processor.classify_toc_only(doc)

                    if result.get("success"):
                        # Reload document to get updated toc_classified
                        updated_doc = db.get_document(args.file_id)
                        updated_toc_classified = (
                            updated_doc.get("sys_toc_classified", "")
                            if updated_doc
                            else ""
                        )

                        # Parse and display the classified TOC
                        if updated_toc_classified:
                            print("\n" + "=" * 80)
                            print("PREDICTED TOC (NEW)")
                            print(f"{'CATEGORY':<25} ENTRY")
                            print("=" * 80)

                            for line in updated_toc_classified.splitlines():
                                if line.strip():
                                    print(format_toc_output(line))

                            print("=" * 80 + "\n")
                            print(
                                f"✓ Classified TOC saved to database for {args.file_id}"
                            )
                        else:
                            print("⚠ No classified TOC found after classification")
                    else:
                        logger.error(f"Classification failed: {result.get('error')}")
                else:
                    # Just compute labels without saving to DB
                    from pipeline.processors.tagging.tagger import SectionTypeTagger

                    section_type_tagger = None
                    for tagger in tagger_processor._taggers:
                        if isinstance(tagger, SectionTypeTagger):
                            section_type_tagger = tagger
                            break

                    if section_type_tagger:
                        toc_entries, labels_by_index = (
                            section_type_tagger._compute_document_toc_labels(doc)
                        )

                        print("\n" + "=" * 80)
                        print("PREDICTED TOC (NEW)")
                        print(f"{'CATEGORY':<25} ENTRY")
                        print("=" * 80)

                        for entry in toc_entries:
                            label = labels_by_index.get(entry["index"], "other")
                            print(format_toc_output(entry, label))

                        print("=" * 80 + "\n")
                        print(
                            "ℹ Classified TOC computed (not saved - use --reparse to save)"
                        )
                    else:
                        logger.error("SectionTypeTagger not found")
            except Exception as e:
                logger.error(f"Prediction failed: {e}")
                import traceback

                traceback.print_exc()
        else:
            print("Skipping prediction (no TOC source text).")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
