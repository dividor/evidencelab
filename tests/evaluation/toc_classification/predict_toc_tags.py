import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List  # noqa: F401

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))  # noqa: E402

from pipeline.processors.tagging.tagger import SectionTypeTagger  # noqa: E402


# Mock Embedding
class MockEmbedding:
    def embed(self, *args, **kwargs):
        return []

    def passage_embed(self, *args, **kwargs):
        return []

    def query_embed(self, *args, **kwargs):
        return []


def run_prediction(input_csv: str, output_csv: str, limit: int = None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("predict_tocs")

    logger.info("Initializing Tagger with Mock Embeddings...")
    tagger = SectionTypeTagger(MockEmbedding())

    logger.info(f"Reading from {input_csv}...")

    processed_rows = []
    headers = []

    try:
        with open(input_csv, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if not headers:
                logger.error("CSV file is empty or missing headers.")
                return

            # Handle TOC column name variations
            toc_col = "TOC"
            if "TOC" not in headers:
                if "TOCS" in headers:
                    toc_col = "TOCS"
                elif "toc" in headers:
                    toc_col = "toc"
                else:
                    logger.error(
                        f"Could not find TOC column. Available headers: {headers}"
                    )
                    return

            logger.info(f"Using '{toc_col}' column for TOC text.")

            # Iterate
            count = 0
            for i, row in enumerate(reader):
                if limit and count >= limit:
                    break

                doc_name = row.get("Document Name", f"Doc {i}")
                toc_text = row.get(toc_col, "")

                if not toc_text:
                    logger.warning(f"Skipping row {i}: Empty TOC")
                    row["TOCS Predicted"] = ""
                    processed_rows.append(row)
                    continue

                logger.info(f"Processing {count+1}: {doc_name[:50]}...")

                # Mock Doc Object for Tagger
                doc = {
                    "id": f"row_{i}",
                    "title": doc_name,
                    "toc": toc_text,
                    "total_pages": 100,  # Default/Dummy if not in CSV
                }

                # Run Classification (Uses new logic: Keyword -> LLM -> Hierarchy)
                try:
                    # Use internal method to get index-based labels
                    toc_entries, labels_by_index = tagger._compute_document_toc_labels(
                        doc
                    )

                    # Re-build for display
                    classified_lines = [
                        tagger._format_toc_line(
                            entry, labels_by_index.get(entry["index"], "other")
                        )
                        for entry in toc_entries
                    ]
                    predicted_text = "\n".join(classified_lines)
                    row["TOCS Predicted"] = predicted_text

                except Exception as e:
                    logger.error(f"Error processing row {i}: {e}")
                    row["TOCS Predicted"] = f"ERROR: {e}"

                processed_rows.append(row)
                count += 1

    except FileNotFoundError:
        logger.error(f"Input file not found: {input_csv}")
        return

    # Write Output
    output_headers = (
        headers + ["TOCS Predicted"] if "TOCS Predicted" not in headers else headers
    )

    logger.info(f"Writing {len(processed_rows)} rows to {output_csv}...")
    with open(output_csv, "w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_headers)
        writer.writeheader()
        writer.writerows(processed_rows)

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Predict TOC classifications for a CSV file."
    )
    parser.add_argument("--input", "-i", default="tocs.csv", help="Input CSV file path")
    parser.add_argument(
        "--output", "-o", default="tocs_predicted.csv", help="Output CSV file path"
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=None, help="Max rows to process"
    )

    args = parser.parse_args()

    run_prediction(args.input, args.output, args.limit)
