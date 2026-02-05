import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Setup path to import shared modules
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent.parent
sys.path.append(str(project_root))

# Reuse logic from sync_azure.py as requested
from scripts.sync.files.sync_azure import generate_sas_token, get_env_vars  # noqa: E402

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def normalize_data_source(data_source: str) -> str:
    return data_source.strip().lower().replace(" ", "_")


def require_value(value: str | None, name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"Missing required value: {name}")


def find_latest_dump(backups_dir: Path, expected_prefix: str):
    """Finds the most recent dump directory for the given prefix."""
    if not backups_dir.exists():
        return None

    dumps = []
    for item in backups_dir.iterdir():
        if item.is_dir() and item.name.startswith(expected_prefix):
            dumps.append(item)

    if not dumps:
        return None

    # Sort by name (timestamp is in name YYYYMMDD_HHMMSS)
    dumps.sort(key=lambda x: x.name, reverse=True)
    return dumps[0]


def has_valid_snapshots(dump_dir: Path) -> bool:
    """Validate that dump directory has non-empty snapshot files."""
    if not dump_dir.exists() or not dump_dir.is_dir():
        return False

    snapshot_files = list(dump_dir.glob("*.snapshot"))
    if not snapshot_files:
        return False

    return all(path.stat().st_size > 0 for path in snapshot_files)


def has_valid_postgres_dump(dump_dir: Path) -> bool:
    """Validate that dump directory has a non-empty .dump file."""
    if not dump_dir.exists() or not dump_dir.is_dir():
        return False
    dump_files = list(dump_dir.glob("*.dump"))
    if len(dump_files) != 1:
        return False
    return dump_files[0].stat().st_size > 0


def upload_zip_with_azcopy(zip_path: Path, account_name, share_name, sas_token):
    logger.info(f"Uploading {zip_path.name} to Azure using AzCopy...")

    try:
        if not zip_path.exists():
            logger.error(f"Zip file not found: {zip_path}")
            return False
        if zip_path.stat().st_size == 0:
            logger.error(f"Zip file is empty: {zip_path}")
            return False

        # Construct Destination URL
        # https://{account}.file.core.windows.net/{share}/db/backups/{filename}?{sas}
        dest_url = (
            f"https://{account_name}.file.core.windows.net/"
            f"{share_name}/db/backups/{zip_path.name}?{sas_token}"
        )

        # We use 'copy' here because we are uploading a single archive file.
        # sync_azure.py uses 'sync' because it handles directory trees.
        cmd = ["azcopy", "copy", str(zip_path), dest_url, "--overwrite=true"]

        # Run AzCopy
        # We allow stdout/stderr to pass through to the console so the user can see progress
        # azcopy automatically handles progress bars in interactive terminals
        result = subprocess.run(cmd, text=True)

        if result.returncode == 0:
            logger.info("Upload Complete.")
            return True
        else:
            logger.error("AzCopy Failed (check output above).")
            return False

    except FileNotFoundError:
        logger.error("Error: 'azcopy' not found in PATH.")
        return False
    except Exception as e:
        logger.error(f"Failed to run AzCopy: {e}")
        return False


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_full_manifest(dump_dir: Path, data_source: str) -> Path:
    snapshots = sorted(dump_dir.glob("*.snapshot"))
    if not snapshots:
        raise RuntimeError(f"No snapshots found in {dump_dir} to build manifest.")

    collections = {}
    for snapshot in snapshots:
        collections[snapshot.name] = {"sha256": compute_sha256(snapshot)}

    manifest = {
        "type": "full",
        "data_source": data_source,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "collections": collections,
    }
    manifest_path = dump_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def write_postgres_manifest(dump_dir: Path, db_name: str) -> Path:
    dumps = sorted(dump_dir.glob("*.dump"))
    if len(dumps) != 1:
        raise RuntimeError(f"Expected one .dump in {dump_dir} to build manifest.")
    manifest = {
        "type": "postgres",
        "database": db_name,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "dump": {"file": dumps[0].name, "sha256": compute_sha256(dumps[0])},
    }
    manifest_path = dump_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def _resolve_ssh_key(key_name: str) -> Path:
    key_path = Path(key_name)
    if not key_path.is_absolute():
        key_path = Path.home() / ".ssh" / key_name
    return key_path


def upload_zip_with_scp(
    zip_path: Path,
    host: str,
    ssh_key: str,
    remote_dir: str,
):
    logger.info(f"Uploading {zip_path.name} to {host} using scp...")

    if not zip_path.exists():
        logger.error(f"Zip file not found: {zip_path}")
        return False
    if zip_path.stat().st_size == 0:
        logger.error(f"Zip file is empty: {zip_path}")
        return False

    key_path = _resolve_ssh_key(ssh_key)
    if not key_path.exists():
        logger.error(f"SSH key not found: {key_path}")
        return False

    destination = f"{host}:{remote_dir.rstrip('/')}/{zip_path.name}"
    cmd = ["scp", "-i", str(key_path), str(zip_path), destination]
    result = subprocess.run(cmd, text=True)
    if result.returncode == 0:
        logger.info("Upload Complete.")
        return True
    logger.error("SCP Failed (check output above).")
    return False


def upload_zip_with_scp_config(zip_path: Path, host: str, remote_dir: str, config: str):
    logger.info(f"Uploading {zip_path.name} to {host} using scp (ssh config)...")

    if not zip_path.exists():
        logger.error(f"Zip file not found: {zip_path}")
        return False
    if zip_path.stat().st_size == 0:
        logger.error(f"Zip file is empty: {zip_path}")
        return False

    config_path = Path(config).expanduser()
    if not config_path.exists():
        logger.error(f"SSH config not found: {config_path}")
        return False

    destination = f"{host}:{remote_dir.rstrip('/')}/{zip_path.name}"
    cmd = ["scp", "-F", str(config_path), str(zip_path), destination]
    result = subprocess.run(cmd, text=True)
    if result.returncode == 0:
        logger.info("Upload Complete.")
        return True
    logger.error("SCP Failed (check output above).")
    return False


def upload_zip_with_gcs(
    zip_path: Path,
    bucket: str,
    prefix: str,
):
    logger.info(f"Uploading {zip_path.name} to gs://{bucket}/{prefix}...")

    if not zip_path.exists():
        logger.error(f"Zip file not found: {zip_path}")
        return False
    if zip_path.stat().st_size == 0:
        logger.error(f"Zip file is empty: {zip_path}")
        return False

    cleaned_prefix = prefix.strip("/")
    destination = f"gs://{bucket}/{cleaned_prefix}/{zip_path.name}"
    cmd = ["gcloud", "storage", "cp", str(zip_path), destination]
    result = subprocess.run(cmd, text=True)
    if result.returncode == 0:
        logger.info("Upload Complete.")
        return True
    logger.error("GCS upload failed (check output above).")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Dump Qdrant, Zip, and Upload to a remote destination."
    )
    parser.add_argument(
        "--source", "-s", help="Path to existing dump directory to upload (optional)"
    )
    parser.add_argument(
        "--source-qdrant",
        required=True,
        help="Path to existing Qdrant dump directory to upload.",
    )
    parser.add_argument(
        "--source-postgres",
        required=True,
        help="Path to existing Postgres dump directory to upload.",
    )
    parser.add_argument(
        "--db",
        default="qdrant",
        choices=["qdrant", "postgres"],
        help="Database to sync (default: qdrant)",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        help="Data source name (required for qdrant)",
    )
    parser.add_argument(
        "--db-name",
        default=os.getenv("POSTGRES_DB"),
        help="Postgres database name (default: POSTGRES_DB)",
    )
    parser.add_argument(
        "--db-user",
        default=os.getenv("POSTGRES_USER"),
        help="Postgres user (default: POSTGRES_USER)",
    )
    parser.add_argument(
        "--db-password",
        default=os.getenv("POSTGRES_PASSWORD"),
        help="Postgres password (default: POSTGRES_PASSWORD)",
    )
    parser.add_argument(
        "--mode",
        default="azure_storage",
        choices=["azure_storage", "scp", "scp_iap", "gcp_storage"],
        help="Upload mode: azure_storage (default) or scp.",
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="Upload a delta backup instead of a full dump.",
    )
    parser.add_argument(
        "--delta-base",
        help="Base dump directory to compute delta against (qdrant_dump_*).",
    )
    parser.add_argument("--scp-host", help="SCP host (e.g., user@hostname).")
    parser.add_argument("--scp-ssh-key", help="SSH key name/path (in ~/.ssh).")
    parser.add_argument("--scp-remote-dir", help="Remote directory for upload.")
    parser.add_argument(
        "--scp-ssh-config",
        default="~/.ssh/config",
        help="SSH config path for scp_iap mode (default: ~/.ssh/config).",
    )
    parser.add_argument("--gcp-bucket", help="GCS bucket name for gcp_storage mode.")
    parser.add_argument(
        "--gcp-prefix",
        default="db/backups",
        help="GCS prefix for uploads (default: db/backups).",
    )
    args = parser.parse_args()
    try:
        if args.delta:
            logger.error("Delta backups are only supported for qdrant.")
            sys.exit(1)
        if not args.data_source:
            logger.error("--data-source is required for qdrant backups.")
            sys.exit(1)
        normalized_source = normalize_data_source(args.data_source)
        if not normalized_source:
            logger.error("Data source cannot be empty.")
            sys.exit(1)
        require_value(args.db_name, "POSTGRES_DB")
        require_value(args.db_user, "POSTGRES_USER")
        require_value(args.db_password, "POSTGRES_PASSWORD")
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if args.mode in {"scp", "scp_iap"}:
        missing = []
        if not args.scp_host:
            missing.append("--scp-host")
        if not args.scp_remote_dir:
            missing.append("--scp-remote-dir")
        if args.mode == "scp" and not args.scp_ssh_key:
            missing.append("--scp-ssh-key")
        if missing:
            logger.error(
                f"Missing required arguments for scp mode: {', '.join(missing)}"
            )
            sys.exit(1)
    elif args.mode == "gcp_storage":
        missing = []
        if not args.gcp_bucket:
            missing.append("--gcp-bucket")
        if missing:
            logger.error(
                f"Missing required arguments for gcp_storage mode: {', '.join(missing)}"
            )
            sys.exit(1)
    else:
        # Reuse environment loading from sync_azure
        account_name, share_name, account_key = get_env_vars()

    backups_dir = project_root / "db" / "backups"

    # 1. Determine Source
    def _sync_source(db: str, source_value: str) -> None:
        source_path = Path(source_value).resolve()
        if not source_path.exists() or not source_path.is_dir():
            logger.error(
                f"Provided source does not exist or is not a directory: {source_path}"
            )
            sys.exit(1)
        if db == "qdrant":
            expected_prefix = f"qdrant_dump_{normalized_source}_"
        else:
            db_name = require_value(args.db_name, "POSTGRES_DB")
            expected_prefix = f"postgres_dump_{db_name}_"
        normalized_name = source_path.name
        if normalized_name.startswith("Post-backfill_"):
            normalized_name = normalized_name.replace("Post-backfill_", "", 1)
        if not normalized_name.startswith(expected_prefix):
            logger.error(
                "Provided source does not match data source. "
                f"Expected prefix '{expected_prefix}'."
            )
            sys.exit(1)
        logger.info(f"Using provided source: {source_path}")

        manifest_path = source_path / "manifest.json"
        if not manifest_path.exists():
            try:
                if db == "qdrant":
                    write_full_manifest(source_path, normalized_source)
                else:
                    db_name = require_value(args.db_name, "POSTGRES_DB")
                    write_postgres_manifest(source_path, db_name)
            except Exception as exc:
                logger.error(f"Failed to write full manifest: {exc}")
                sys.exit(1)

        logger.info(f"\n>>> ZIPPING {source_path.name}")
        zip_base_name = str(backups_dir / source_path.name)
        if os.path.exists(zip_base_name + ".zip"):
            logger.info(f"Zip already exists: {zip_base_name}.zip")
            zip_path = str(zip_base_name + ".zip")
        else:
            zip_path = shutil.make_archive(
                base_name=zip_base_name,
                format="zip",
                root_dir=source_path.parent,
                base_dir=source_path.name,
            )

        zip_path_obj = Path(zip_path)
        if not zip_path_obj.exists():
            logger.error(
                "Archive not found on disk. "
                "If you are running inside Docker, re-run with:\n"
                "docker compose exec api python scripts/sync/db/sync_backup_to_remote.py "
                f"--data-source {normalized_source}"
            )
            sys.exit(1)
        if zip_path_obj.stat().st_size == 0:
            logger.error(f"Archive is empty: {zip_path_obj}")
            sys.exit(1)
        size_mb = zip_path_obj.stat().st_size / 1024 / 1024
        logger.info(f"Archive ready: {zip_path_obj.name} ({size_mb:.2f} MB)")

        if args.mode == "scp":
            logger.info("\n>>> UPLOADING VIA SCP")
            success = upload_zip_with_scp(
                zip_path_obj,
                args.scp_host,
                args.scp_ssh_key,
                args.scp_remote_dir,
            )
        elif args.mode == "scp_iap":
            logger.info("\n>>> UPLOADING VIA SCP (IAP/SSH CONFIG)")
            success = upload_zip_with_scp_config(
                zip_path_obj,
                args.scp_host,
                args.scp_remote_dir,
                args.scp_ssh_config,
            )
        elif args.mode == "gcp_storage":
            logger.info("\n>>> UPLOADING TO GCS")
            success = upload_zip_with_gcs(
                zip_path_obj,
                args.gcp_bucket,
                args.gcp_prefix,
            )
        else:
            logger.info("\n>>> UPLOADING TO AZURE")
            sas_token = generate_sas_token(account_name, share_name, account_key)
            success = upload_zip_with_azcopy(
                zip_path_obj, account_name, share_name, sas_token
            )

        if success:
            logger.info("\nSUCCESS: Backup synced to Azure.")
            try:
                os.remove(zip_path_obj)
                logger.info("Cleaned up local zip file.")
            except Exception:
                pass
        else:
            logger.info("\nFAILED: Upload failed.")
            sys.exit(1)

    _sync_source("qdrant", args.source_qdrant)
    _sync_source("postgres", args.source_postgres)


if __name__ == "__main__":
    main()
