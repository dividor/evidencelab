import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# Add project root to path for imports
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent.parent
sys.path.append(str(project_root))

import logging  # noqa: E402

from pipeline.db import Database  # noqa: E402
from pipeline.db.config import load_datasources_config  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def resolve_data_source_candidates(data_source: Optional[str]) -> list[str]:
    if not data_source:
        return []
    config = load_datasources_config()
    datasources = config.get("datasources", {})
    for name, details in datasources.items():
        if name.lower() == data_source.lower():
            mapped = details.get("data_subdir") or data_source
            candidates = [mapped, data_source]
            seen = set()
            ordered = []
            for candidate in candidates:
                normalized = candidate.lower().replace(" ", "_")
                if normalized not in seen:
                    seen.add(normalized)
                    ordered.append(candidate)
            return ordered
    return [data_source]


def select_data_source(client, data_source: Optional[str]) -> Optional[str]:
    candidates = resolve_data_source_candidates(data_source)
    if not candidates:
        return None
    for candidate in candidates:
        suffix = candidate.lower().replace(" ", "_")
        documents_collection = f"documents_{suffix}"
        chunks_collection = f"chunks_{suffix}"
        try:
            documents_count = client.count(
                collection_name=documents_collection, exact=True
            ).count
            chunks_count = client.count(
                collection_name=chunks_collection, exact=True
            ).count
        except Exception:
            continue
        if documents_count > 0 or chunks_count > 0:
            if candidate != candidates[0]:
                logger.warning(
                    "Mapped datasource '%s' is empty. Using '%s' instead.",
                    candidates[0],
                    candidate,
                )
            return candidate
    return candidates[0]


def dump_qdrant(
    output_dir: Path, data_source: Optional[str] = None, prefix: str = ""
) -> Optional[Path]:
    # 1. Connect
    logger.info("Connecting to Qdrant...")
    # Increase timeout for dump operations to 1 hour
    os.environ["QDRANT_CLIENT_TIMEOUT"] = "3600"
    try:
        candidates = resolve_data_source_candidates(data_source)
        initial_source = candidates[0] if candidates else None
        db = Database(data_source=initial_source)
        client = db.client
        selected_source = select_data_source(client, data_source)
        if selected_source is None and candidates:
            selected_source = candidates[0]
        if selected_source != db.data_source:
            db = Database(data_source=selected_source)
            client = db.client
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return None

    # 2. Prepare Output Directory
    # Default to db/backups relative to project root
    if str(output_dir) == "backups":
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        output_dir = project_root / "db" / "backups"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_source = db.data_source.lower().replace(" ", "_")
    dir_name = f"qdrant_dump_{sanitized_source}_{timestamp}"
    if prefix:
        dir_name = f"{prefix}{dir_name}"
    backup_path = output_dir / dir_name
    backup_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Backup location: {backup_path}")

    # 3. Identify Collections
    collections = [db.documents_collection, db.chunks_collection]

    # Verify collections have data before dumping
    for collection in collections:
        try:
            count_result = client.count(collection_name=collection, exact=True)
            if count_result.count == 0:
                logger.error(
                    f"Collection '{collection}' is empty. "
                    "Aborting to avoid creating an empty backup."
                )
                return None
        except Exception as exc:
            logger.error(f"Failed to count collection '{collection}': {exc}")
            return None

    # 4. Snapshot and Download
    dump_ok = True
    for collection in collections:
        logger.info(f"\nProcessing collection: {collection}")

        try:
            # Create Snapshot
            logger.info("  Creating snapshot (this may take a while)...")
            snapshot_info = client.create_snapshot(collection_name=collection)
            snapshot_name = snapshot_info.name
            logger.info(f"  Snapshot created: {snapshot_name}")

            # Download Snapshot
            # Get base URL robustly
            if hasattr(client, "rest_uri"):
                base_url = client.rest_uri
            elif hasattr(client, "_client") and hasattr(client._client, "base_url"):
                # Fallback for some versions
                base_url = str(client._client.base_url)
            else:
                # Fallback to env var if client inspection fails
                base_url = os.getenv("QDRANT_HOST", "http://localhost:6333")
                # Handle missing scheme
                if not base_url.startswith("http"):
                    base_url = f"http://{base_url}"

            # Strip trailing slash
            base_url = base_url.rstrip("/")

            # HOSTNAME FIX: If running on host (not in docker),
            # 'db' or 'qdrant' hostname won't resolve.
            # Force localhost if we detect this mismatch.
            if not os.path.exists("/.dockerenv"):
                if "://db" in base_url:
                    logger.info(
                        "  Detected 'db' hostname while running on host. "
                        "Swapping to 'localhost'."
                    )
                    base_url = base_url.replace("://db", "://localhost")
                elif "://qdrant" in base_url:
                    logger.info(
                        "  Detected 'qdrant' hostname while running on host. "
                        "Swapping to 'localhost'."
                    )
                    base_url = base_url.replace("://qdrant", "://localhost")

            # Construct download URL
            download_url = (
                f"{base_url}/collections/{collection}/snapshots/{snapshot_name}"
            )
            target_file = backup_path / f"{collection}.snapshot"

            logger.info(f"  Downloading to {target_file}...")

            headers = {}
            api_key = os.getenv("QDRANT_API_KEY")
            if api_key:
                headers["api-key"] = api_key

            with requests.get(download_url, headers=headers, stream=True) as r:
                r.raise_for_status()
                with open(target_file, "wb") as f:
                    shutil.copyfileobj(r.raw, f)

            if target_file.stat().st_size == 0:
                logger.error(
                    "  Downloaded snapshot is empty. "
                    "Aborting to avoid creating an invalid backup."
                )
                dump_ok = False
            else:
                logger.info("  Download complete.")

        except Exception as e:
            logger.error(f"  Failed to dump {collection}: {e}")
            dump_ok = False

    if not dump_ok:
        logger.error("\nDump failed. Backup is incomplete.")
        return None

    logger.info(f"\nAll operations complete. Backup at: {backup_path}")
    return backup_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump Qdrant collections to snapshots")
    parser.add_argument("--output", "-o", default="backups", help="Output directory")
    parser.add_argument(
        "--data-source", type=str, help="Data source name (e.g., 'uneg')"
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Prefix to add to backup directory name.",
    )
    args = parser.parse_args()

    success = dump_qdrant(
        Path(args.output), data_source=args.data_source, prefix=args.prefix
    )
    sys.exit(0 if success else 1)
