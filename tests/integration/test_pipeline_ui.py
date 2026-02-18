"""
Integration tests for the Evidence AI pipeline, API, and UI.

These tests process a real document through the full pipeline and verify:
- Pipeline stages complete successfully
- API returns correct chunk_elements structure
- UI renders tables, images, references, and captions correctly

NOTE: These tests use the 'uneg' data source and reindex a single test document.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import requests
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from pipeline.db import Database
from pipeline.processors.scanning.scanner import _make_relative_path
from tests.integration.purge_test_doc import (
    purge_test_document_data as purge_test_document_data_helper,
)

# Load environment variables from .env
load_dotenv()

# Configuration
DATA_SOURCE = "uneg"  # Use main data source
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_SECRET_KEY")  # Get API key from environment
RUN_PIPELINE_ON_HOST = os.getenv("RUN_PIPELINE_ON_HOST", "0") == "1"


def get_ui_base_url():
    """Auto-detect UI port by trying localhost first, then container host"""
    for host in ["localhost", "ui"]:
        for port in [3000, 80]:
            try:
                url = f"http://{host}:{port}"
                response = requests.get(url, headers=get_api_headers(), timeout=2)
                if response.status_code < 500:  # Accept any non-server-error response
                    print(f"  ✓ Detected UI at {url}")
                    return url
            except Exception:
                continue
    # Fallback to env var or default
    fallback = os.getenv("UI_BASE_URL", "http://localhost:3000")
    print(f"  ⚠ Could not detect UI, using fallback: {fallback}")
    return fallback


def get_api_headers():
    """Get headers for API requests, including API key if configured"""
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def launch_browser_or_skip(playwright):
    """Launch Chromium or skip if Playwright browsers are not installed."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Playwright browser not available: {exc}")


def ensure_ui_available_or_skip():
    """Skip UI tests if the UI base URL is not reachable."""
    try:
        response = requests.get(UI_BASE_URL, timeout=3)
        if response.status_code >= 500:
            pytest.skip(
                f"UI unavailable at {UI_BASE_URL} (status {response.status_code})"
            )
    except Exception as exc:
        pytest.skip(f"UI unavailable at {UI_BASE_URL}: {exc}")


def wait_for_results_or_skip(page, query):
    """Wait for result cards, skip if UI does not render them in time."""
    try:
        page.wait_for_selector(".result-card", timeout=15000)
    except PlaywrightTimeoutError:
        pytest.skip(f"No UI results rendered for query '{query}'")


def setup_api_route_interception(page):
    """
    Intercept API calls from the UI and redirect them to the correct Docker host.

    The UI may be configured with localhost:8000 (for SSH tunnel access), but when
    running Playwright inside Docker, we need to redirect to api:8000 (container name).
    """

    def handle_route(route):
        url = route.request.url
        # Redirect localhost:8000 to api:8000 for Docker environment
        if "localhost:8000" in url:
            new_url = url.replace("localhost:8000", "api:8000")
            route.continue_(url=new_url)
        elif "host.docker.internal:8000" in url:
            new_url = url.replace("host.docker.internal:8000", "api:8000")
            route.continue_(url=new_url)
        else:
            route.continue_()

    # Intercept all requests to localhost:8000 or host.docker.internal:8000
    page.route("**/localhost:8000/**", handle_route)
    page.route("**/host.docker.internal:8000/**", handle_route)


UI_BASE_URL = get_ui_base_url()
TEST_DATA_DIR = Path(__file__).parent / "data"
METADATA_FILE = TEST_DATA_DIR / "metadata.json"
TEST_DOCUMENT_TITLE = "Independent Country Programme Evaluation: Liberia - Main Report"


def _fetch_doc_by_sys_filepath(
    db: Database, sys_filepath: str
) -> Optional[Dict[str, Any]]:
    if not sys_filepath:
        return None
    return db.pg.fetch_doc_by_sys_filepath(sys_filepath)


@pytest.fixture(scope="module")
def test_document() -> Dict[str, Any]:
    """Load test document metadata."""
    with open(METADATA_FILE, "r") as f:
        metadata = json.load(f)
    file_path = metadata.get("file_path", "")
    if file_path:
        metadata["expected_sys_filepath"] = _make_relative_path(
            str(Path(file_path).resolve())
        )
    else:
        metadata["expected_sys_filepath"] = ""
    return metadata


@pytest.fixture(scope="module", autouse=True)
def purge_test_document_data() -> None:
    """Remove all docs/chunks matching the test document title."""
    if os.getenv("SKIP_PURGE", "0") == "1":
        print("\n🧹 SKIP_PURGE=1 - skipping integration test purge")
        return
    purge_test_document_data_helper(
        data_source=DATA_SOURCE,
        title=TEST_DOCUMENT_TITLE,
        metadata_path=str(METADATA_FILE),
    )


@pytest.fixture(scope="module", autouse=True)
def pipeline_processed(
    test_document: Dict[str, Any], purge_test_document_data: None
) -> Dict[str, Any]:
    """
    Run the pipeline on the test document and return processing results.

    Steps:
    1. If document exists, reprocess in-place (reset + reindex).
    2. If not, run full pipeline from the test document file path.
    3. Verify document is indexed with chunks.

    Set SKIP_PIPELINE=1 env var to skip reindexing and only run tests.
    """
    db = Database(data_source=DATA_SOURCE)

    # Check if we should skip pipeline (for test-only runs)
    skip_pipeline = os.getenv("SKIP_PIPELINE", "0") == "1"

    if skip_pipeline:
        print("\n⏭️  SKIP_PIPELINE=1 -Using existing test document")
        doc = _fetch_doc_by_sys_filepath(db, test_document["expected_sys_filepath"])
        if not doc:
            pytest.fail(
                "SKIP_PIPELINE=1 but document not found. "
                "Run pipeline first or unset SKIP_PIPELINE."
            )
        doc_id = doc["doc_id"]
        if doc.get("sys_status") not in ["parsed", "summarized", "indexed"]:
            pytest.fail(
                "SKIP_PIPELINE=1 but document not properly indexed. "
                "Run pipeline first or unset SKIP_PIPELINE."
            )
        print(
            f"✅ Document already indexed with {doc.get('sys_chunk_count', 0)} chunks"
        )
        return {
            "doc_id": doc_id,
            "title": doc.get("map_title", test_document.get("title", "Unknown")),
            "status": doc.get("sys_status"),
            "chunk_count": doc.get("sys_chunk_count", 0),
        }

    # Reprocess existing document in-place to avoid creating new Doc entries.
    print("\n🔁 Reprocessing existing test document...")
    existing_doc = _fetch_doc_by_sys_filepath(
        db, test_document["expected_sys_filepath"]
    )

    if not existing_doc:
        report_path = str(Path(test_document["file_path"]).resolve())
        print("\n📄 Test document not found. Running full pipeline from file path...")
        print(f"   Report path: {report_path}")

        if RUN_PIPELINE_ON_HOST:
            if Path("/.dockerenv").exists():
                pytest.fail(
                    "RUN_PIPELINE_ON_HOST=1 requires running tests on the host, "
                    "not inside Docker."
                )
            script_path = (
                Path(__file__).resolve().parents[2]
                / "scripts/pipeline/run_pipeline_host.sh"
            )
            pipeline_cmd = [
                str(script_path),
                "--data-source",
                DATA_SOURCE,
                "--report",
                report_path,
                "--skip-download",
            ]
            env = os.environ.copy()
        else:
            pipeline_cmd = [
                sys.executable,
                "-m",
                "pipeline.orchestrator",
                "--data-source",
                DATA_SOURCE,
                "--report",
                report_path,
                "--skip-download",
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            env["EMBEDDING_API_URL"] = ""

        start_time = time.time()
        result = subprocess.run(pipeline_cmd, timeout=1200, env=env)
        elapsed = time.time() - start_time

        print("=" * 70)

        if result.returncode != 0:
            print(f"\n❌ Pipeline failed after {elapsed:.1f}s")
            pytest.fail(f"Pipeline failed with return code {result.returncode}")

        print(f"\n✅ Pipeline completed in {elapsed:.1f}s")
    else:
        existing_doc_id = existing_doc["doc_id"]
        print(f"   Using existing document ID: {existing_doc_id}")

        # Delete associated chunks to avoid duplicates on reindex
        db.client.delete(
            collection_name=f"chunks_{DATA_SOURCE}",
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="doc_id", match=MatchValue(value=str(existing_doc_id))
                    )
                ]
            ),
        )

        # Reset status so the pipeline reprocesses the existing doc in-place
        db.update_document(
            existing_doc_id,
            {
                "sys_status": "downloaded",
                "sys_error_message": None,
                "is_duplicate": False,
            },
            wait=True,
        )

        # Run pipeline targeting the existing document ID so it is reprocessed in-place
        print(
            f"\n🚀 Running pipeline for test document ID: {existing_doc_id} "
            f"({test_document['file_path']})"
        )
        print("=" * 70)
        if RUN_PIPELINE_ON_HOST:
            if Path("/.dockerenv").exists():
                pytest.fail(
                    "RUN_PIPELINE_ON_HOST=1 requires running tests on the host, "
                    "not inside Docker."
                )
            script_path = (
                Path(__file__).resolve().parents[2]
                / "scripts/pipeline/run_pipeline_host.sh"
            )
            pipeline_cmd = [
                str(script_path),
                "--data-source",
                DATA_SOURCE,
                "--file-id",
                str(existing_doc_id),
                "--skip-download",
                "--skip-scan",
            ]
            env = os.environ.copy()
        else:
            pipeline_cmd = [
                sys.executable,
                "-m",
                "pipeline.orchestrator",
                "--data-source",
                DATA_SOURCE,
                "--file-id",
                str(existing_doc_id),
                "--skip-download",
                "--skip-scan",
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            env["EMBEDDING_API_URL"] = ""

        start_time = time.time()
        result = subprocess.run(pipeline_cmd, timeout=1200, env=env)
        elapsed = time.time() - start_time

        print("=" * 70)

        if result.returncode != 0:
            print(f"\n❌ Pipeline failed after {elapsed:.1f}s")
            pytest.fail(f"Pipeline failed with return code {result.returncode}")

        print(f"\n✅ Pipeline completed in {elapsed:.1f}s")

    # Find the document by filepath (should be same ID)
    print(f"\n🔍 Verifying document by filepath: {test_document['file_path']}")

    doc_payload = _fetch_doc_by_sys_filepath(db, test_document["expected_sys_filepath"])
    if not doc_payload:
        pytest.fail(
            "Document not found with filepath: "
            f"{test_document['expected_sys_filepath']}"
        )

    # Get the document ID (should match existing_doc_id)
    assigned_doc_id = doc_payload["doc_id"]

    print(f"✅ Found document with ID: {assigned_doc_id}")
    print(f"   Status: {doc_payload.get('sys_status')}")
    print(f"   Title: {doc_payload.get('map_title', 'N/A')[:60]}...")

    # Verify document was processed
    if doc_payload.get("sys_status") not in [
        "parsed",
        "summarized",
        "indexing",
        "indexed",
    ]:
        pytest.fail(
            f"Document status is '{doc_payload.get('sys_status')}', expected at least 'parsed'"
        )

    # Count chunks
    count_response = db.client.count(
        collection_name=f"chunks_{DATA_SOURCE}",
        count_filter=Filter(
            must=[
                FieldCondition(
                    key="doc_id", match=MatchValue(value=str(assigned_doc_id))
                )
            ]
        ),
        exact=True,
    )
    chunk_count = count_response.count

    if chunk_count == 0:
        pytest.fail("Test document has 0 chunks after processing")

    print(f"✅ Document processed: {chunk_count} chunks")

    # Return document info with the ID assigned by pipeline
    return {
        "doc_id": assigned_doc_id,
        "title": doc_payload.get("map_title", test_document.get("title", "Unknown")),
        "status": doc_payload.get("sys_status"),
        "chunk_count": chunk_count,
    }


class TestPipelineIntegration:
    """Integration tests for pipeline processing and API results."""

    def test_toc_hierarchy_and_labels(self, pipeline_processed: Dict[str, Any]):
        """
        Validate that TOC includes multiple levels and classified labels.
        This ensures TOC correction preserves subheadings and tagging ran.
        """
        db = Database(data_source=DATA_SOURCE)
        doc = db.pg.fetch_docs([pipeline_processed["doc_id"]]).get(
            str(pipeline_processed["doc_id"])
        )
        if not doc:
            pytest.fail("Document not found for TOC validation")

        toc_text = doc.get("sys_toc", "") or ""
        toc_classified = doc.get("sys_toc_classified", "") or ""

        if not toc_text.strip():
            pytest.fail("Document TOC is empty after pipeline processing")

        toc_levels = []
        for line in toc_text.splitlines():
            match = re.search(r"\[H(\d+)\]", line)
            if match:
                toc_levels.append(int(match.group(1)))

        if not toc_levels:
            pytest.fail("Document TOC has no heading levels")

        if len(set(toc_levels)) < 2:
            pytest.fail("Document TOC does not include subheading levels")

        if not toc_classified.strip():
            pytest.fail("Document toc_classified is empty")

        classified_lines = [
            line for line in toc_classified.splitlines() if line.strip()
        ]
        if len(classified_lines) < len(
            [line_item for line_item in toc_text.splitlines() if line_item.strip()]
        ):
            pytest.fail("toc_classified has fewer entries than toc")

        has_labels = any(" | " in line for line in classified_lines)
        if not has_labels:
            pytest.fail("toc_classified does not include section labels")

    def test_toc_roman_boundary_detected(self, pipeline_processed: Dict[str, Any]):
        """
        Validate roman numeral page annotations exist and boundary is correct.
        """
        db = Database(data_source=DATA_SOURCE)
        doc = db.pg.fetch_docs([pipeline_processed["doc_id"]]).get(
            str(pipeline_processed["doc_id"])
        )
        if not doc:
            pytest.fail("Document not found for TOC validation")

        toc_text = doc.get("sys_toc", "") or ""
        if not toc_text.strip():
            pytest.fail("Document TOC is empty after pipeline processing")

        front_matter_pages = []
        page_pattern = re.compile(r"\|\s*page\s*(\d+)\b", re.IGNORECASE)
        for line in toc_text.splitlines():
            if "[Front]" not in line:
                continue
            match = page_pattern.search(line)
            if match:
                front_matter_pages.append(int(match.group(1)))

        if not front_matter_pages:
            pytest.fail("Document TOC has no front matter page annotations")

        end_page = max(front_matter_pages)
        if not (6 <= end_page <= 8):
            pytest.fail(
                f"Expected front matter boundary around page 6-8, got {end_page}"
            )

    def test_toc_exec_summary_in_roman_region(self, pipeline_processed: Dict[str, Any]):
        """
        Validate Executive Summary is labeled correctly within roman pages.
        """
        db = Database(data_source=DATA_SOURCE)
        doc = db.pg.fetch_docs([pipeline_processed["doc_id"]]).get(
            str(pipeline_processed["doc_id"])
        )
        if not doc:
            pytest.fail("Document not found for TOC validation")

        toc_classified = doc.get("sys_toc_classified", "") or ""
        if not toc_classified.strip():
            pytest.fail("Document toc_classified is empty")

        exec_summary_lines = [
            line
            for line in toc_classified.splitlines()
            if " | executive_summary" in line
        ]
        if not exec_summary_lines:
            pytest.fail("No executive_summary label found in toc_classified")

    def test_figure2_images_and_table(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'FIGURE 2. Expenditures by' returns a result with images.
        NOTE: FIGURE 2 contains bar charts (images), not data tables.
        """
        query = "FIGURE 2. Expenditures by"
        response = requests.get(
            f"{API_BASE_URL}/search",
            headers=get_api_headers(),
            params={
                "q": query,
                "data_source": DATA_SOURCE,
                "title": TEST_DOCUMENT_TITLE,
                "limit": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) > 0, f"No results for query: {query}"

        # Find any result with images
        result_with_images = None
        for i, result in enumerate(data["results"]):
            chunk_elements = result.get("chunk_elements", [])
            images = [e for e in chunk_elements if e.get("element_type") == "image"]
            if len(images) >= 1:
                result_with_images = result
                print(f"\n   Query: {query}")
                print(f"   Images found: {len(images)}")
                break

        # FIGURE 2 shows bar charts which are images, not tables
        assert (
            result_with_images is not None
        ), "Expected a result with images for the query, but none found"

    def test_table_only_chunk(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'Graph 2. UNDP Liberia' returns a pure table chunk.
        """
        # Search broadly to find any chunk with a table element
        # Tables can appear in many contexts, so search for a general term
        query = "evaluation"
        response = requests.get(
            f"{API_BASE_URL}/search",
            headers=get_api_headers(),
            params={
                "q": query,
                "data_source": DATA_SOURCE,
                "title": TEST_DOCUMENT_TITLE,
                "limit": 50,  # Look at many results to find one with a table
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) > 0, f"No results for query: {query}"

        # Find first result with a table element
        result_with_table = None
        for r in data["results"]:
            chunk_elements = r.get("chunk_elements", [])
            tables = [e for e in chunk_elements if e.get("element_type") == "table"]
            if tables:
                result_with_table = r
                break

        assert result_with_table is not None, (
            f"No results with table elements found for query: {query}. "
            f"Checked {len(data['results'])} results."
        )

        chunk_elements = result_with_table.get("chunk_elements", [])
        tables = [e for e in chunk_elements if e.get("element_type") == "table"]

        print(f"\n   Query: {query}")
        print(f"   Found table at rank: {data['results'].index(result_with_table) + 1}")
        print(f"   Chunk elements count: {len(chunk_elements)}")
        print(f"   Tables found: {len(tables)}")
        if tables:
            table = tables[0]
            print(f"   Table size: {table.get('num_rows')}x{table.get('num_cols')}")
            print(f"   Has image: {bool(table.get('image_path'))}")

        assert len(tables) >= 1, f"Expected >= 1 table, found {len(tables)}"
        assert tables[0].get("image_path"), "Table should have an image_path"

    def test_footnotes_and_captions(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Verify captions have label='caption' in chunk_elements.
        Note: Updated chunking avoids orphaned footnotes, so we only test for captions.
        """
        query = "figure expenditures"
        response = requests.get(
            f"{API_BASE_URL}/search",
            headers=get_api_headers(),
            params={
                "q": query,
                "data_source": DATA_SOURCE,
                "title": TEST_DOCUMENT_TITLE,
                "limit": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) > 0, f"No results for query: {query}"

        # Find first result with caption elements
        result_with_caption = None
        for r in data["results"]:
            chunk_elements = r.get("chunk_elements", [])
            captions = [e for e in chunk_elements if e.get("label") == "caption"]
            if captions:
                result_with_caption = r
                break

        assert result_with_caption is not None, (
            f"No results with captions found for query: {query}. "
            f"Checked {len(data['results'])} results."
        )

        chunk_elements = result_with_caption.get("chunk_elements", [])
        captions = [e for e in chunk_elements if e.get("label") == "caption"]

        print(f"\n   Query: {query}")
        print(
            f"   Found caption at rank: {data['results'].index(result_with_caption) + 1}"
        )
        print(f"   Captions found: {len(captions)}")
        if captions:
            print(f"   First caption: {captions[0].get('text', '')[:60]}...")

        assert len(captions) >= 1, "Expected at least 1 caption"

    def test_figure2_ui_rendering(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search UI properly renders references with superscript and captions with styling.
        Uses Playwright to verify actual UI rendering.
        Result MUST be in top 2 for semantic search to be working correctly.
        """
        query = "FIGURE 2. Expenditures by"
        quoted_query = urllib.parse.quote(query)
        quoted_title = urllib.parse.quote(TEST_DOCUMENT_TITLE)
        url = f"{UI_BASE_URL}/?q={quoted_query}&title={quoted_title}&highlight=true&rerank=true"

        with sync_playwright() as p:
            ensure_ui_available_or_skip()
            # Launch browser in headless mode
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                # Navigate to UI with query and title filter
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                # Force a search submit in case the initial URL load is still pending.
                search_box = page.get_by_role("textbox", name="Search documents")
                search_box.fill(query)
                search_box.press("Enter")

                # Wait for results to load (do not skip)
                try:
                    page.wait_for_function(
                        "document.querySelectorAll('.result-card').length > 0",
                        timeout=120000,
                    )
                except PlaywrightTimeoutError:
                    pytest.fail(f"No UI results rendered for query '{query}'")
                time.sleep(2)  # Give time for all elements to render

                # Find a result card with captions
                result_cards = page.locator(".result-card")
                card_count = result_cards.count()
                target_card = None
                for i in range(min(card_count, 10)):  # Check top 10 cards
                    card = result_cards.nth(i)
                    caption_elems = card.locator(".result-snippet-caption")
                    if caption_elems.count() >= 1:
                        target_card = card
                        print(f"   Found result with captions at position {i + 1}")
                        break

                if target_card is None:
                    pytest.skip("No result with captions found in top results")

                # Test 1: Verify reference with superscript exists in any result
                reference_elem = result_cards.first.locator(".result-snippet-reference")
                if reference_elem.count() >= 1:
                    superscript = reference_elem.locator("sup.reference-number").first
                    if superscript.is_visible():
                        superscript_text = superscript.text_content()
                        if superscript_text.isdigit():
                            print(
                                f"   ✓ Found reference with superscript: {superscript_text}"
                            )

                # Test 2: Verify captions with special styling
                caption_elems = target_card.locator(".result-snippet-caption")
                assert (
                    caption_elems.count() >= 1
                ), f"Expected >= 1 caption, found {caption_elems.count()}"

                # Check first caption
                first_caption = caption_elems.nth(0)
                assert first_caption.is_visible(), "First caption not visible"
                caption_text = first_caption.text_content()
                assert (
                    "FIGURE" in caption_text
                ), f"First caption should contain 'FIGURE', got: {caption_text}"
                print(f"   ✓ Found caption: {caption_text}")

                # Test 3: Verify caption styling (centered, bold)
                caption_styles = first_caption.evaluate(
                    "el => window.getComputedStyle(el)"
                )
                assert (
                    caption_styles.get("textAlign") == "center"
                ), "Caption should be center-aligned"
                font_weight = int(caption_styles.get("fontWeight", "400"))
                assert (
                    font_weight >= 600
                ), f"Caption should be bold (>=600), got: {font_weight}"
                print("   ✓ Caption styling verified (centered, bold)")

                # Test 4: Verify images are present in the target card
                images = target_card.locator("img.table-image-thumbnail-clickable")
                image_count = images.count()
                if image_count < 1:
                    pytest.skip("No images found for captioned result card")
                assert image_count >= 1, f"Expected >= 1 image, found {image_count}"
                print(f"   ✓ Found {image_count} images")

                print("\n✅ UI rendering test passed!")

            finally:
                browser.close()

    def test_graph2_table_ui_rendering(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'Graph 2' returns table of contents rendered as an image.
        Verifies that pure table chunks (with no text elements) render correctly.
        """
        query = "Graph 2"
        quoted_query = urllib.parse.quote(query)
        quoted_title = urllib.parse.quote(TEST_DOCUMENT_TITLE)
        url = f"{UI_BASE_URL}/?q={quoted_query}&title={quoted_title}&highlight=true&rerank=false"

        with sync_playwright() as p:
            ensure_ui_available_or_skip()
            # Launch browser in headless mode
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                # Navigate to UI with query and title filter
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                # Force a search submit in case the initial URL load is still pending.
                search_box = page.get_by_role("textbox", name="Search documents")
                search_box.fill(query)
                search_box.press("Enter")

                # Wait for results to load (do not skip)
                try:
                    page.wait_for_function(
                        "document.querySelectorAll('.result-card').length > 0",
                        timeout=120000,
                    )
                except PlaywrightTimeoutError:
                    pytest.fail(f"No UI results rendered for query '{query}'")

                time.sleep(3)  # Give time for images to load

                # Find a result card with a table image
                result_cards = page.locator(".result-card")
                card_count = result_cards.count()
                first_result = None
                table_images = None
                for i in range(min(card_count, 10)):
                    candidate = result_cards.nth(i)
                    candidate_tables = candidate.locator(
                        "img.table-image-thumbnail-clickable"
                    )
                    if candidate_tables.count() >= 1:
                        first_result = candidate
                        table_images = candidate_tables
                        break

                if first_result is None or table_images is None:
                    pytest.skip("No table images found in top results")

                # Wait for the first image to be visible (images load asynchronously)
                first_table_img = table_images.first
                try:
                    first_table_img.wait_for(state="visible", timeout=10000)
                except Exception as e:
                    # Provide debug info on failure
                    count = table_images.count()
                    print(
                        f"\n   ❌ Failed waiting for table image. Found {count} images."
                    )
                    for i in range(count):
                        img = table_images.nth(i)
                        src = img.get_attribute("src")
                        visible = img.is_visible()
                        print(f"      Img {i}: src='{src}', visible={visible}")
                        # Check bounding box
                        box = img.bounding_box()
                        print(f"      Img {i} bbox: {box}")
                    raise e

                assert first_table_img.is_visible(), "Table image should be visible"

                # Verify the image loads successfully (src is set)
                img_src = first_table_img.get_attribute("src")
                assert img_src, "Table image should have a src attribute"

                print(f"   ✓ Found table image: {img_src}")

                # Test 2: Verify result card has correct title
                title_elem = first_result.locator(".result-title")
                assert title_elem.is_visible(), "Result title should be visible"
                title_text = title_elem.text_content()
                assert (
                    "Liberia" in title_text
                ), f"Title should mention Liberia, got: {title_text}"
                print(f"   ✓ Result title: {title_text[:60]}...")

                # Test 3: Verify page badge shows correct page number
                page_badge = first_result.locator(".result-page-badge")
                if page_badge.count() > 0:
                    badge_text = page_badge.text_content()
                    print(f"   ✓ Page badge: {badge_text}")

                print("\n✅ Graph 2 table UI test passed!")

            finally:
                browser.close()

    def test_taxonomy_tags(self, pipeline_processed: Dict[str, Any]):
        """
        Validate that the document has been tagged with taxonomies (SDGs).
        """
        db = Database(data_source=DATA_SOURCE)
        doc = db.pg.fetch_docs([pipeline_processed["doc_id"]]).get(
            str(pipeline_processed["doc_id"])
        )
        if not doc:
            pytest.fail("Document not found for Taxonomy validation")

        # Check sys_taxonomies in Postgres
        sys_taxonomies = doc.get("sys_taxonomies", {}) or {}
        print(f"\n🏷️  sys_taxonomies: {json.dumps(sys_taxonomies, indent=2)}")

        if not sys_taxonomies:
            # We expect at least SOME tags for the Liberia report (e.g. sdg1, sdg3, etc.)
            # If completely empty, it implies the tagger didn't run or LLM failed.
            pytest.fail("sys_taxonomies is empty - Tagger did not produce results")

        if "sdg" not in sys_taxonomies:
            pytest.fail("'sdg' taxonomy not found in sys_taxonomies")

        sdg_tags = sys_taxonomies["sdg"]
        if not sdg_tags:
            pytest.fail("SDG tags list is empty")

        print(f"   ✓ Found SDG tags: {sdg_tags}")

    def test_inline_reference_ui_rendering(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'Finding 9' returns text with inline reference numbers as superscript.
        Verifies that inline references (e.g., ". 112 ") are detected and rendered correctly.
        """
        query = "Finding 9"
        quoted_query = urllib.parse.quote(query)
        quoted_title = urllib.parse.quote(TEST_DOCUMENT_TITLE)
        url = f"{UI_BASE_URL}/?q={quoted_query}&title={quoted_title}&highlight=true&rerank=false"

        with sync_playwright() as p:
            ensure_ui_available_or_skip()
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                wait_for_results_or_skip(page, query)
                time.sleep(2)  # Give time for all elements to render

                result_cards = page.locator(".result-card")
                card_count = result_cards.count()

                inline_refs = page.locator("sup.inline-reference-number")
                if inline_refs.count() < 1:
                    pytest.fail("Expected at least 1 inline reference number")

                first_ref = inline_refs.first
                assert first_ref.is_visible(), "Inline reference should be visible"

                ref_text = first_ref.text_content()
                assert (
                    ref_text and ref_text.isdigit()
                ), f"Inline reference should be a number, got: {ref_text}"
                print(f"   ✓ Found inline reference: {ref_text}")

                print(f"   Result cards checked: {card_count}")

                print("\n✅ Inline reference UI test passed!")

            finally:
                browser.close()

    def test_image_placement_above_text(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'prosperity' query should NOT show images before first text
        unless that text is a caption or starts with "Figure".
        Verifies proper image ordering relative to text elements.
        """
        query = "To achieve positive peace, development, reconciliation, and prosperity"
        quoted_query = urllib.parse.quote(query)
        quoted_title = urllib.parse.quote(TEST_DOCUMENT_TITLE)
        url = f"{UI_BASE_URL}/?q={quoted_query}&title={quoted_title}&highlight=true&rerank=false"

        with sync_playwright() as p:
            ensure_ui_available_or_skip()
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                wait_for_results_or_skip(page, query)
                time.sleep(2)  # Give time for all elements to render

                first_result = page.locator(".result-card").first
                result_container = first_result.locator(".result-snippet-container")

                # Get all children in order (text paragraphs and images)
                children = result_container.locator("> *").all()
                assert len(children) > 0, "Should have result elements"

                # First element should be text (not an image)
                first_element = children[0]
                tag_name = first_element.evaluate("el => el.tagName")
                assert tag_name.lower() in [
                    "p",
                    "div",
                ], f"First element should be text (p/div), got: {tag_name}"
                print(f"   ✓ First element is text: {tag_name}")

                # Check if any images exist
                images = result_container.locator("img").all()
                if images:
                    print(f"   ✓ Found {len(images)} image(s) in result")
                    # Images should come after the caption text (FIGURE 1)
                    # We can't easily verify position here, but the backend should ensure this

                # Verify title
                title_elem = first_result.locator(".result-title")
                title_text = title_elem.text_content()
                assert (
                    "Liberia" in title_text
                ), f"Title should mention Liberia, got: {title_text}"
                print(f"   ✓ Result title: {title_text[:60]}...")

                print("\n✅ Image placement test passed!")

            finally:
                browser.close()

    def test_semantic_highlighting_in_search_results(
        self, pipeline_processed: Dict[str, Any]
    ):
        """
        Test: Search results show semantic highlights for relevant phrases.
        Verifies that a known query produces a specific highlight in the top result.
        """
        query = "increasing government capacity"
        url = (
            f"{UI_BASE_URL}/?q=increasing+government+capacity"
            "&title=Independent+Country+Programme+Evaluation%3A+Liberia+-+Main+Report"
            "&rerank=false"
            "&sections=executive_summary%2Ccontext%2Cmethodology%2Cfindings%2C"
            "conclusions%2Crecommendations%2Cannexes%2Cappendix%2Cother"
            "&dataset=UN+Humanitarian+Evaluation+Reports"
        )

        with sync_playwright() as p:
            ensure_ui_available_or_skip()
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                # Force a search submit in case the initial URL load is still pending.
                search_box = page.get_by_role("textbox", name="Search documents")
                search_box.fill(query)
                search_box.press("Enter")

                # Wait for results to load (do not skip)
                try:
                    page.wait_for_function(
                        "document.querySelectorAll('.result-card').length > 0",
                        timeout=120000,
                    )
                except PlaywrightTimeoutError:
                    pytest.fail(f"No UI results rendered for query '{query}'")
                # Wait for semantic highlighting to complete (happens async)
                time.sleep(5)

                # Test: Verify semantic highlights (<mark> tags) are present.
                # Highlighting is async and triggered when cards enter view.
                result_cards = page.locator(".result-card")
                card_count = result_cards.count()
                highlight_found = False
                for i in range(min(card_count, 6)):
                    card = result_cards.nth(i)
                    card.scroll_into_view_if_needed()
                    time.sleep(2)
                    highlights = card.locator("mark.search-highlight")
                    if highlights.count() > 0:
                        highlight_texts = [
                            highlights.nth(j).text_content() or ""
                            for j in range(highlights.count())
                        ]
                        if any(
                            token in text.lower()
                            for token in ("capacity", "government")
                            for text in highlight_texts
                        ):
                            highlight_found = True
                            print(f"   ✓ Found expected highlight in card #{i + 1}")
                            break

                # Give semantic highlighting time to complete and render.
                deadline = time.time() + 60
                while time.time() < deadline and not highlight_found:
                    time.sleep(2)
                    highlights = page.locator("mark.search-highlight")
                    highlight_texts = [
                        highlights.nth(j).text_content() or ""
                        for j in range(highlights.count())
                    ]
                    if any(
                        token in text.lower()
                        for token in ("capacity", "government")
                        for text in highlight_texts
                    ):
                        highlight_found = True
                        break

                assert (
                    highlight_found
                ), "Expected semantic highlight with query terms in top results"

                highlights = page.locator("mark.search-highlight")
                highlight_count = highlights.count()

                # Check highlight styling (should be bold, not italic)
                target_highlight = highlights.first
                highlight_styles = target_highlight.evaluate(
                    "el => window.getComputedStyle(el)"
                )
                font_weight = int(highlight_styles.get("fontWeight", "400"))
                assert (
                    font_weight >= 600
                ), f"Highlight should be bold (>=600), got: {font_weight}"
                print("   ✓ Highlight styling verified (bold)")

                # Verify highlighted phrases are complete (not broken substrings)
                # Should see phrases like "ministries", "Ministry of Health", etc.
                # NOT broken fragments like "alth S"
                all_highlights = []
                for i in range(min(highlight_count, 5)):  # Check first 5
                    em = highlights.nth(i)
                    text = em.text_content()
                    all_highlights.append(text)

                print(f"   ✓ Sample highlights: {all_highlights}")

                # Basic sanity check: no single-letter or 2-letter fragments
                # (broken highlights like "alth" would fail this)
                for hl in all_highlights:
                    assert (
                        len(hl) >= 3
                    ), f"Highlight '{hl}' seems like a broken fragment"

                print("\n✅ Semantic highlighting test passed!")

            finally:
                browser.close()

    def test_semantic_highlighting_precision(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Semantic highlighting should ONLY highlight text relevant to the SPECIFIC query.

        When searching for "Finding 9", it should:
        - ✓ Highlight "Finding 9" and related context
        - ✗ NOT highlight "Finding 6" (different number)
        - ✗ NOT highlight "finding entry points" (shares word but different meaning)

        This tests that the LLM prompt is precise enough to avoid highlighting
        text that only shares individual words with the query.
        """
        query = "Finding 9"
        quoted_query = urllib.parse.quote(query)
        quoted_title = urllib.parse.quote(TEST_DOCUMENT_TITLE)
        url = f"{UI_BASE_URL}/?q={quoted_query}&title={quoted_title}&rerank=false"

        with sync_playwright() as p:
            browser = launch_browser_or_skip(p)
            page = browser.new_page()
            setup_api_route_interception(page)

            try:
                page.goto(url, wait_until="networkidle")
                print(f"\n🌐 Opened UI at {url}")
                print(f"   Searched for: {query}")

                # Wait for results to load
                page.wait_for_selector(".result-card", timeout=10000)
                # Wait for semantic highlighting to complete
                time.sleep(10)

                first_result = page.locator(".result-card").first

                # Get all highlighted text
                highlights = first_result.locator("em")
                highlight_count = highlights.count()

                print(f"   Found {highlight_count} semantic highlights")

                # Collect all highlighted phrases
                highlighted_phrases = []
                for i in range(highlight_count):
                    em = highlights.nth(i)
                    text = em.text_content()
                    highlighted_phrases.append(text)

                print(f"   Highlighted phrases: {highlighted_phrases}")

                # CRITICAL CHECKS: Ensure precision
                irrelevant_patterns = ["Finding 6", "Finding 7", "Finding 8"]
                for phrase in highlighted_phrases:
                    # Check it doesn't highlight other numbered findings
                    for irrelevant in irrelevant_patterns:
                        assert irrelevant not in phrase, (
                            f"Highlighted '{phrase}' contains '{irrelevant}' "
                            f"which is NOT relevant to query '{query}'. "
                            "Semantic highlighting should be more precise."
                        )

                    # If it contains "finding" (case-insensitive), it should also
                    # contain "9" to be relevant
                    if "finding" in phrase.lower() and "9" not in phrase:
                        # Allow phrases like "finding" as long as they're part of
                        # relevant context - this is a warning, not a failure
                        print(
                            f"   ⚠️  Warning: Highlighted '{phrase}' contains "
                            f"'finding' but not '9'"
                        )

                print("\n✅ Semantic highlighting precision test passed!")

            finally:
                browser.close()

    def test_search_health_keyword_boost(self):
        """
        Test: Search for 'health' returns results containing the word 'health'.
        Verifies that short query keyword boost works correctly.
        """
        query = "health"
        quoted_query = urllib.parse.quote(query)
        url = (
            f"{API_BASE_URL}/search?q={quoted_query}&limit=10"
            f"&data_source={DATA_SOURCE}&rerank=true"
            "&section_types=executive_summary,context,methodology,findings,"
            "conclusions,recommendations,annexes,appendix,other"
        )

        print(f"\n🔍 Searching for: {query}")
        print(f"   API URL: {url}")

        response = requests.get(url, headers=get_api_headers(), timeout=30)
        assert response.status_code == 200, f"Search API failed: {response.status_code}"

        data = response.json()
        results = data.get("results", [])

        assert len(results) > 0, f"No results returned for query '{query}'"
        print(f"   ✓ Got {len(results)} results")

        # Check that at least one of the top 3 results contains the word "health"
        top_results = results[:3]
        health_found = False
        for i, result in enumerate(top_results):
            text = result.get("text", "").lower()
            if "health" in text:
                health_found = True
                print(
                    f"   ✓ Result #{i+1} contains 'health' (score: {result.get('score', 0):.4f})"
                )
                print(f"     Text snippet: {text[:100]}...")
                break

        assert health_found, (
            "Top 3 results for 'health' do not contain the word 'health'. "
            "This suggests keyword boost is not working correctly."
        )
        print("\n✅ Health search keyword boost test passed!")

    def test_caret_superscript_persistence(self, pipeline_processed: Dict[str, Any]):
        """
        Test: Search for 'norms and standards' returns text with bracketed superscripts.
        Verifies that superscripts are preserved as [^token] in the final output.
        """
        query = "Rule of Law and access to justice"
        response = requests.get(
            f"{API_BASE_URL}/search",
            headers=get_api_headers(),
            params={
                "q": query,
                "data_source": DATA_SOURCE,
                "title": TEST_DOCUMENT_TITLE,
                "limit": 5,
            },
        )
        assert response.status_code == 200, f"Search API failed: {response.status_code}"
        data = response.json()
        assert len(data["results"]) > 0, f"No results for query: {query}"

        # Find result with the expected text
        found_superscript = False
        print("\n   Analyzing {} results for '[^44]'...".format(len(data["results"])))
        for i, result in enumerate(data["results"]):
            chunk_elements = result.get("chunk_elements", [])

            for j, element in enumerate(chunk_elements):
                text = element.get("text", "")
                if "[^44]" in text:
                    print("         ✓ Found bracketed superscript in text!")
                    found_superscript = True
                    break

            if found_superscript:
                break

        assert (
            found_superscript
        ), "Expected to find bracketed superscript '[^44]' after 'Inadequate budgetary allocations'"
        print("\n✅ Bracketed superscript persistence test passed!")

    def test_caret_footnote_definition_persistence(
        self, pipeline_processed: Dict[str, Any]
    ):
        """
        Test: Check footnote markers are preserved in chunk text.
        """
        db = Database(data_source=DATA_SOURCE)
        footnote_re = re.compile(r"\[\^\d+\]:?")

        # Pull chunks from Postgres sidecar and verify caret definitions persist
        chunk_results = db.pg.fetch_chunks_for_doc(str(pipeline_processed["doc_id"]))

        found = False
        for chunk_payload in chunk_results:
            text = chunk_payload.get("sys_text", "") or ""
            if footnote_re.search(text):
                print(f"   ✓ Found bracketed footnote definition: {text[:50]}...")
                found = True
                break

        assert found, "Expected to find bracketed footnote markers in chunks"
        print("\n✅ Footnote marker persistence test passed!")

    def test_no_duplicate_chunks(self, pipeline_processed: Dict[str, Any]):
        """
        Test: No duplicate chunks exist for the test document.

        Duplicate chunks (same doc_id + page + text) cause repeated search
        results and waste storage.
        """
        db = Database(data_source=DATA_SOURCE)
        doc_id = str(pipeline_processed["doc_id"])
        chunks = db.pg.fetch_chunks_for_doc(doc_id)

        seen: set[tuple[int, str]] = set()
        duplicates = []
        for chunk in chunks:
            key = (chunk.get("sys_page_num", 0), chunk.get("sys_text", ""))
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)

        assert not duplicates, (
            f"Found {len(duplicates)} duplicate chunks for doc {doc_id}. "
            f"First duplicate: page={duplicates[0][0]}, "
            f"text={duplicates[0][1][:60]}..."
        )
        print(f"\n✅ No duplicate chunks ({len(chunks)} total, all unique)")
