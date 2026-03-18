"""
download.py - Download a small set of World Bank PDFs for demo purposes.

This is a simplified version of the World Bank downloader
(pipeline/integration/evidencelab-ai-integration/worldbank/download.py)
that fetches a handful of documents so users can quickly test the full
Evidence Lab pipeline without waiting for a large download.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import requests
from dateutil import parser as date_parser  # type: ignore[import-untyped]

# Add project root to path to allow imports from pipeline
sys.path.append(str(Path(__file__).resolve().parents[2]))

try:
    from pipeline.pipeline_utils.sanitization import sanitize_filename
except ImportError:
    # Fallback if running outside of pipeline context
    def sanitize_filename(name):
        return "".join(
            [c for c in name if c.isalpha() or c.isdigit() or c in (" ", "-", "_")]
        ).strip()


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("DemoDownloader")


class DemoDownloader:
    """Download a small number of World Bank documents for demo/testing."""

    BASE_API_URL = "https://search.worldbank.org/api/v3/wds"

    REPORT_TYPES = [
        "Publication",
        "Report",
        "Brief",
        "IEG Evaluation",
    ]

    QUERY_TERMS = [
        "integrity",
        "fraud",
        "corruption",
        "governance",
    ]

    def __init__(self, data_dir="./data/demo", limit=3, delay=1.0, page_size=10):
        self.data_dir = Path(data_dir)
        self.limit = limit
        self.delay = delay
        self.page_size = page_size
        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }
        )

    def _build_query_params(self, offset=0):
        """Build parameters for the World Bank API."""
        qterm = " OR ".join(self.QUERY_TERMS)
        docty = "^".join(self.REPORT_TYPES)

        params = {
            "format": "json",
            "rows": self.page_size,
            "os": offset,
            "seccl": "Public",
            "qterm": qterm,
            "docty_exact": docty,
            "sort": "docdt_desc",
        }
        return params

    def _get_api_data(self, offset=0):
        """Fetch a page of results from the API with retries."""
        params = self._build_query_params(offset=offset)

        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Querying API offset={offset} (Attempt {attempt+1}/{max_retries})..."
                )
                encoded_params = urlencode(params, quote_via=quote)
                url = f"{self.BASE_API_URL}?{encoded_params}"
                response = self.session.get(url, timeout=30)

                if response.status_code in [500, 502, 503, 504]:
                    logger.warning(f"Server error {response.status_code}. Retrying...")
                    time.sleep(base_delay * (2**attempt))
                    continue

                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Error querying API: {e}")
                if attempt < max_retries - 1:
                    time.sleep(base_delay * (2**attempt))
                else:
                    return None
        return None

    def _download_file(self, url, target_path):
        """Download a file with streaming."""
        try:
            with self.session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return True, None
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False, str(e)

    # Fields where comma-separated values should be converted to semicolons.
    SEMICOLON_DELIMIT_FIELDS = {"subtopic", "teratopic", "historic_topic"}

    @classmethod
    def normalize_metadata(cls, metadata):
        """Normalize World Bank API metadata in-place.

        1. Numbered-dict-of-dicts (e.g. authors, keywd, geo_regions, docna,
           sectr) are flattened:
           - Multi-entry: joined with ``"; "`` into a single string.
           - Single-entry wrapper (e.g. repnme): unwrapped to the scalar.
        2. Comma-delimited fields (subtopic, teratopic, historic_topic) are
           converted to semicolon-delimited.

        Returns *metadata* (mutated) for convenience.
        """
        for key in list(metadata.keys()):
            value = metadata[key]

            # --- Flatten numbered-dict-of-dicts --------------------------
            if isinstance(value, dict):
                inner_keys = list(value.keys())
                all_numeric = all(k.isdigit() for k in inner_keys)

                if all_numeric:
                    parts = []
                    for idx in sorted(inner_keys, key=int):
                        inner = value[idx]
                        if isinstance(inner, dict) and len(inner) == 1:
                            parts.append(str(next(iter(inner.values()))).strip())
                        else:
                            parts.append(str(inner).strip())
                    metadata[key] = "; ".join(parts)

                elif len(inner_keys) == 1:
                    sole_key = inner_keys[0]
                    if isinstance(value[sole_key], str):
                        metadata[key] = value[sole_key]
                    elif sole_key == "cdata!" or sole_key == sole_key:
                        metadata[key] = str(value[sole_key])

            # --- Comma -> semicolon for selected fields -------------------
            if key in cls.SEMICOLON_DELIMIT_FIELDS and isinstance(metadata[key], str):
                metadata[key] = "; ".join(
                    p.strip() for p in metadata[key].split(",") if p.strip()
                )

        return metadata

    def _save_metadata(self, doc_data, save_dir, base_filename):
        """Save standard metadata JSON."""
        metadata = doc_data.copy()

        metadata.update(
            {
                "source": "worldbank",
                "download_date": datetime.now().isoformat(),
                "listing_url": self.BASE_API_URL,
            }
        )

        self.normalize_metadata(metadata)

        meta_path = save_dir / f"{base_filename}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return meta_path

    def _save_error(self, doc_data, save_dir, base_filename, error_message):
        """Save error file."""
        error_data = {
            "id": doc_data.get("id"),
            "title": doc_data.get("display_title"),
            "url": doc_data.get("pdfurl"),
            "error_message": str(error_message),
            "timestamp": datetime.now().isoformat(),
        }

        err_path = save_dir / f"{base_filename}.error"
        with open(err_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)

    def run(self):
        """Main execution loop - downloads up to `limit` documents."""
        logger.info(f"Starting demo download. Target: {self.limit} documents")

        total_processed = 0
        offset = 0

        while total_processed < self.limit:
            data = self._get_api_data(offset=offset)

            if not data or "documents" not in data:
                logger.warning("No documents found in response or API error.")
                break

            documents_dict = data.get("documents", {})

            if offset == 0:
                total_available = data.get("total", 0)
                logger.info(f"Total reports available: {total_available}")

            if not documents_dict:
                logger.info("No more documents available.")
                break

            for doc_id, doc in documents_dict.items():
                if total_processed >= self.limit:
                    break

                pdf_url = doc.get("pdfurl")
                if not pdf_url:
                    continue

                # Determine year
                doc_date_str = doc.get("docdt")
                year = "Unknown"
                if doc_date_str:
                    try:
                        dt = date_parser.parse(doc_date_str)
                        year = str(dt.year)
                    except Exception:
                        pass

                majdocty = (
                    doc.get("majdocty", "Uncategorized").strip() or "Uncategorized"
                )
                safe_majdocty = sanitize_filename(majdocty)

                title = doc.get("display_title") or "Untitled"
                repnb = doc.get("repnb", doc_id)

                sanitized_title = sanitize_filename(title)
                if len(sanitized_title) > 150:
                    sanitized_title = sanitized_title[:150]

                base_filename = f"{sanitized_title}_{repnb}"

                # Save under data/demo/pdfs/<MajDocTy>/<Year>/
                save_dir = self.data_dir / "pdfs" / safe_majdocty / year
                save_dir.mkdir(parents=True, exist_ok=True)

                target_pdf_path = save_dir / f"{base_filename}.pdf"

                if target_pdf_path.exists():
                    logger.info(f"Skipping {base_filename} - already exists")
                    if not (save_dir / f"{base_filename}.json").exists():
                        self._save_metadata(doc, save_dir, base_filename)
                    total_processed += 1
                    continue

                logger.info(
                    f"[{total_processed + 1}/{self.limit}] Downloading: {title} ({year})"
                )
                success, error_msg = self._download_file(pdf_url, target_pdf_path)

                self._save_metadata(doc, save_dir, base_filename)

                if not success:
                    self._save_error(
                        doc, save_dir, base_filename, error_msg or "Download failed"
                    )

                total_processed += 1
                time.sleep(self.delay)

            total_available = data.get("total", 0)
            offset += self.page_size

            if offset >= total_available:
                break

            time.sleep(self.delay)

        logger.info(
            f"Demo download complete. {total_processed} documents downloaded to {self.data_dir}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download a small set of World Bank documents for demo"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of documents to download (default: 3)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./data/demo",
        help="Output directory (default: ./data/demo)",
    )

    args = parser.parse_args()

    downloader = DemoDownloader(
        data_dir=args.data_dir,
        limit=args.limit,
    )
    downloader.run()
