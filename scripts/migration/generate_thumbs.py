"""
Generate thumbnails for all parsed documents.

This script:
1. Scans the parsed folder on disk for document directories
2. For each parsed document, generates a thumbnail from the first page
3. Saves thumbnail.png in the parsed folder

Usage:
    python scripts/migration/generate_thumbs.py
    python scripts/migration/generate_thumbs.py --overwrite
    python scripts/migration/generate_thumbs.py --data-source uneg
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv

# Add project root to path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_thumbnail(pdf_path: str, output_folder: str) -> bool:
    """
    Generate a thumbnail from the first page of a PDF.

    Args:
        pdf_path: Path to the source PDF
        output_folder: Directory where thumbnail.png will be saved

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if PDF exists
        if not os.path.exists(pdf_path):
            logger.warning(f"  ⚠ PDF not found: {pdf_path}")
            return False

        # Open the PDF
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            logger.warning(f"  ⚠ PDF has no pages: {pdf_path}")
            doc.close()
            return False

        # Get the first page
        page = doc[0]

        # Calculate zoom to get ~300px max dimension
        rect = page.rect
        max_dimension = max(rect.width, rect.height)
        target_size = 300
        zoom = target_size / max_dimension

        # Create transformation matrix for rendering
        mat = fitz.Matrix(zoom, zoom)

        # Render page to pixmap (image)
        pix = page.get_pixmap(matrix=mat)

        # Ensure output folder exists
        os.makedirs(output_folder, exist_ok=True)

        # Save as PNG
        thumbnail_path = Path(output_folder) / "thumbnail.png"
        pix.save(str(thumbnail_path))

        doc.close()
        return True

    except Exception as e:
        logger.error(f"  ✗ Failed to generate thumbnail: {e}")
        return False


def find_pdf_in_folder(folder_path: Path) -> Path | None:
    """
    Find the PDF file in a parsed folder (may be symlink or regular file).

    Args:
        folder_path: Path to the parsed document folder

    Returns:
        Path to PDF file, or None if not found
    """
    # Look for any PDF file in the folder
    for pdf_file in folder_path.glob("*.pdf"):
        return pdf_file
    return None


def generate_thumbnails_from_disk(data_source="uneg", overwrite=False):
    """
    Generate thumbnails by scanning the parsed folder on disk.

    Args:
        data_source: Data source name (e.g., 'uneg', 'worldbank')
        overwrite: If True, regenerate thumbnails even if they exist
    """
    data_mount_path = os.getenv("DATA_MOUNT_PATH", "./data")
    parsed_base = Path(data_mount_path) / data_source / "parsed"

    if not parsed_base.exists():
        logger.error(f"Parsed folder not found: {parsed_base}")
        return

    logger.info(f"Scanning parsed folders in: {parsed_base}")

    total_count = 0
    success_count = 0
    skip_count = 0
    error_count = 0

    # Walk through agency/year/document structure
    for agency_dir in parsed_base.iterdir():
        if not agency_dir.is_dir():
            continue

        for year_dir in agency_dir.iterdir():
            if not year_dir.is_dir():
                continue

            for doc_dir in year_dir.iterdir():
                if not doc_dir.is_dir():
                    continue

                total_count += 1
                doc_name = doc_dir.name

                # Check if thumbnail already exists
                thumbnail_path = doc_dir / "thumbnail.png"
                if thumbnail_path.exists() and not overwrite:
                    logger.debug(f"  ⊙ Skipping {doc_name}: Thumbnail already exists")
                    skip_count += 1
                    continue

                # Find PDF file in folder
                pdf_path = find_pdf_in_folder(doc_dir)
                if not pdf_path:
                    logger.warning(f"  ⚠ Skipping {doc_name}: No PDF file found")
                    skip_count += 1
                    continue

                # Resolve symlink if needed
                if pdf_path.is_symlink():
                    pdf_path = pdf_path.resolve()

                    # Fix Docker paths (/app/data -> DATA_MOUNT_PATH)
                    pdf_str = str(pdf_path)
                    if pdf_str.startswith("/app/data/"):
                        pdf_path = Path(data_mount_path) / pdf_str[len("/app/data/") :]

                # Generate thumbnail
                logger.info(f"  Generating thumbnail for: {doc_name}")
                if generate_thumbnail(str(pdf_path), str(doc_dir)):
                    logger.info(f"    ✓ Generated: {thumbnail_path}")
                    success_count += 1
                else:
                    logger.error("    ✗ Failed to generate thumbnail")
                    error_count += 1

    logger.info("\n" + "=" * 60)
    logger.info("Thumbnail Generation Summary:")
    logger.info(f"  Total documents scanned: {total_count}")
    logger.info(f"  Thumbnails generated:    {success_count}")
    logger.info(f"  Skipped:                 {skip_count}")
    logger.info(f"  Errors:                  {error_count}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Generate thumbnails for all parsed documents."
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="uneg",
        help="Data source name (default: uneg)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate thumbnails even if they already exist",
    )

    args = parser.parse_args()

    generate_thumbnails_from_disk(
        data_source=args.data_source, overwrite=args.overwrite
    )


if __name__ == "__main__":
    main()
