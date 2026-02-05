import glob
import json
import logging
import os

from pipeline.db import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def cleanup_db(db: Database):
    """
    Scan DB for documents that point to .error files but are marked as valid.
    This fixes cases where ID mismatch prevents filename-based sync.
    """
    logger.info("Running DB-side consistency check...")

    # We need to scroll all docs, or at least filtered ones
    # For safety, let's look at 'downloaded' and 'parsing' status

    from qdrant_client import models

    total_fixed = 0

    # Filter for candidates (status that implies success)
    scroll_filter = models.Filter(
        should=[
            models.FieldCondition(
                key="status", match=models.MatchValue(value="downloaded")
            ),
            models.FieldCondition(
                key="status", match=models.MatchValue(value="parsing")
            ),
            models.FieldCondition(
                key="status", match=models.MatchValue(value="processing")
            ),
            models.FieldCondition(
                key="status", match=models.MatchValue(value="parse_failed")
            ),
            models.FieldCondition(
                key="status", match=models.MatchValue(value="processing_failed")
            ),
            models.FieldCondition(key="status", match=models.MatchValue(value="error")),
        ]
    )

    offset = None
    while True:
        points, next_offset = db.client.scroll(
            collection_name=db.documents_collection,
            scroll_filter=scroll_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        for point in points:
            filepath = point.payload.get("filepath", "")
            if filepath and filepath.endswith(".error"):
                logger.warning(f"🚨 Found invalid document in DB: {point.id}")
                logger.warning(f"   Status: {point.payload.get('status')}")
                logger.warning(f"   Filepath: {filepath}")

                # Fix it
                db.update_document(
                    point.id,
                    {
                        "status": "download_error",
                        "error_details": "Fixed by sync_errors: Invalid filepath ending in .error",
                    },
                )
                total_fixed += 1

        offset = next_offset
        if offset is None:
            break

    logger.info(
        f"DB Consistency Check Complete. Fixed {total_fixed} invalid documents."
    )


def sync_errors(data_source="uneg"):
    """
    Scan PDF directory for .error files and update DB status.
    """
    # Initialize DB
    db = Database(data_source=data_source)

    # Path to PDFs
    # Note: Orchestrator sets data_dir = data/{source}
    # Download script uses data/{source}/pdfs
    pdf_dir = f"data/{data_source}/pdfs"

    if not os.path.exists(pdf_dir):
        logger.error(f"Directory not found: {pdf_dir}")
        return

    logger.info(f"Scanning {pdf_dir} for .error files...")

    # improved matching using pathlib or glob recursive
    error_files = glob.glob(os.path.join(pdf_dir, "**/*.error"), recursive=True)
    logger.info(f"Found {len(error_files)} error files.")

    updated_count = 0
    not_found_count = 0

    for error_file in error_files:
        try:
            basename = os.path.basename(error_file)
            name_part = os.path.splitext(basename)[0]  # e.g. "Title_12345"

            # Extract DocID (last part after underscore)
            # Example: "My_Report_Title_12345.error" -> "12345"
            if "_" in name_part:
                doc_id = name_part.rsplit("_", 1)[-1]
            else:
                # Fallback: maybe the filename IS the ID
                doc_id = name_part

            # Read error content
            error_details = "Unknown error"
            try:
                with open(error_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.startswith("{") and content.endswith("}"):
                        data = json.loads(content)
                        error_details = data.get("error_message") or data.get(
                            "error", str(data)
                        )
                    else:
                        error_details = content
            except Exception as e:
                logger.warning(f"Could not read content of {basename}: {e}")

            # Verify doc exists in DB
            doc = db.get_document(doc_id)
            if not doc:
                # Try to restore from JSON metadata
                json_file = os.path.splitext(error_file)[0] + ".json"
                if os.path.exists(json_file):
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            metadata = json.load(f)

                        # Fix ID type if needed (DB expects int usually)
                        metadata["id"] = doc_id
                        metadata["status"] = "download_error"
                        metadata["error_details"] = error_details
                        metadata["download_error_at"] = os.path.getmtime(error_file)

                        logger.info(f"Restoring orphaned doc {doc_id} from JSON...")
                        db.upsert_document(doc_id, metadata)
                        updated_count += 1
                        continue
                    except Exception as e:
                        logger.error(f"Failed to restore {doc_id} from JSON: {e}")

                not_found_count += 1
                continue

            # Update DB if status isn't already 'download_error'
            curr_status = doc.get("status")

            if curr_status != "download_error":
                logger.info(f"Updating {doc_id}: '{curr_status}' -> 'download_error'")
                db.update_document(
                    doc_id,
                    {
                        "status": "download_error",
                        "error_details": error_details,
                        "download_error_at": os.path.getmtime(error_file),
                    },
                )
                updated_count += 1
            else:
                # Status is already correct, maybe update details if missing?
                if not doc.get("error_details"):
                    logger.info(
                        f"Updating details for {doc_id} (already download_error)"
                    )
                    db.update_document(doc_id, {"error_details": error_details})
                    updated_count += 1

        except Exception as e:
            logger.error(f"Failed to process {error_file}: {e}")

    logger.info("Sync complete.")
    logger.info(f"  Skipped (Doc not found): {not_found_count}")

    # Run DB cleanup
    cleanup_db(db)


if __name__ == "__main__":
    sync_errors()
