import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from azure.storage.fileshare import ShareDirectoryClient
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from scripts.sync.db.apply_qdrant_delta import apply_delta

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# --- Embedded Segment Unpacker Script ---
# This python script will be executed INSIDE the restore worker container
# to recursively unpack inner segment tarballs.
UNPACKER_SCRIPT = """
import os
import tarfile
import shutil
from pathlib import Path

def unpack(collection_path):
    segments_dir = Path(collection_path) / "0" / "segments"
    if not segments_dir.exists():
        print(f"No segments dir: {segments_dir}")
        return

    print(f"Scanning {segments_dir}...")
    tar_files = list(segments_dir.glob("*.tar"))

    for tar_path in tar_files:
        segment_uuid = tar_path.stem
        target_dir = segments_dir / segment_uuid
        target_dir.mkdir(exist_ok=True)

        print(f"Processing segment: {segment_uuid}")
        try:
            temp_extract_dir = segments_dir / f"temp_{segment_uuid}"
            temp_extract_dir.mkdir(exist_ok=True)

            with tarfile.open(tar_path, "r:") as tar:
                tar.extractall(path=temp_extract_dir)

            source_content = temp_extract_dir / "snapshot" / "files"
            if source_content.exists():
                for item in source_content.iterdir():
                    shutil.move(str(item), str(target_dir))

                # Some snapshots include mutable_id_tracker.* only. Keep them,
                # and copy to id_tracker.* when missing for compatibility.
                mutable_mappings = target_dir / "mutable_id_tracker.mappings"
                mutable_versions = target_dir / "mutable_id_tracker.versions"
                id_mappings = target_dir / "id_tracker.mappings"
                id_versions = target_dir / "id_tracker.versions"
                if mutable_mappings.exists() and not id_mappings.exists():
                    shutil.copy2(mutable_mappings, id_mappings)
                if mutable_versions.exists() and not id_versions.exists():
                    shutil.copy2(mutable_versions, id_versions)

                print(f"  Extracted to {target_dir}")
            else:
                print(f"  WARN: snapshot/files not found in {tar_path.name}")

            shutil.rmtree(temp_extract_dir)
            os.remove(tar_path) # Remove original tar

        except Exception as e:
            print(f"  Error unpacking {tar_path.name}: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        unpack(sys.argv[1])
"""


def load_config():
    # scripts/sync/db -> repo root (4 levels up)
    root_dir = Path(__file__).resolve().parents[3]
    env_path = root_dir / ".env"
    load_dotenv(env_path)

    config = {
        "account_name": os.getenv("STORAGE_ACCOUNT_NAME"),
        "share_name": os.getenv("STORAGE_SHARE_NAME"),
        "account_key": os.getenv("STORAGE_ACCOUNT_KEY"),
    }
    return config


def load_datasources_config_local(root_dir: Path) -> dict:
    config_path = root_dir / "config.json"
    if not config_path.exists():
        legacy_path = root_dir / "datasources.config.json"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            logger.warning("Config file %s not found. Using defaults.", config_path)
            return {}
    with open(config_path, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_collection_name(snapshot_stem: str) -> str:
    prefix = None
    suffix = snapshot_stem
    if snapshot_stem.startswith("documents_"):
        prefix = "documents_"
        suffix = snapshot_stem[len(prefix) :]
    elif snapshot_stem.startswith("chunks_"):
        prefix = "chunks_"
        suffix = snapshot_stem[len(prefix) :]

    if not prefix:
        return snapshot_stem

    root_dir = Path(__file__).resolve().parents[3]
    datasources = load_datasources_config_local(root_dir).get("datasources", {})
    suffix_normalized = suffix.lower().replace(" ", "_")
    for name, details in datasources.items():
        name_slug = name.lower().replace(" ", "_")
        if suffix_normalized == name_slug:
            data_subdir = details.get("data_subdir", "").lower().replace(" ", "_")
            if data_subdir:
                return f"{prefix}{data_subdir}"
    return snapshot_stem


def run_command(cmd, cwd=None):
    """Runs a shell command and returns True if success."""
    try:
        subprocess.run(cmd, shell=True, check=True, cwd=cwd)  # nosec B602
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e}")
        return False


def compose_base_command(use_dev: bool = False) -> str:
    if use_dev:
        return "docker compose -f docker-compose.yml"
    compose_file = os.getenv("COMPOSE_FILE", "docker-compose.prod.yml")
    return f"docker compose -f {compose_file}"


def resolve_db_mount(project_root: Path) -> Path:
    env_mount = os.getenv("DB_DATA_MOUNT")
    if env_mount:
        return Path(env_mount).resolve()

    try:
        result = subprocess.run(
            "docker inspect qdrant --format '{{json .Mounts}}'",
            shell=True,
            check=True,
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        mounts = json.loads(result.stdout.strip())
        for mount in mounts:
            if mount.get("Destination") == "/qdrant/storage":
                return Path(mount.get("Source")).resolve().parent
    except Exception as exc:
        logger.error(f"Failed to resolve DB mount from docker: {exc}")

    raise RuntimeError(
        "Unable to resolve DB mount. Set DB_DATA_MOUNT or ensure qdrant is running."
    )


def wait_for_qdrant(timeout_seconds: int = 120, interval_seconds: int = 5) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    qdrant_url = "http://localhost:6333"
    while time.time() < deadline:
        try:
            client = QdrantClient(url=qdrant_url)
            client.get_collections()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(interval_seconds)
    raise RuntimeError(f"Qdrant did not become ready: {last_error}")


def wait_for_collections(
    collection_names: list[str],
    timeout_seconds: int = 300,
    interval_seconds: int = 5,
) -> None:
    deadline = time.time() + timeout_seconds
    missing = set(collection_names)
    last_error: Exception | None = None
    client = QdrantClient(url="http://localhost:6333")
    while time.time() < deadline:
        try:
            existing = {c.name for c in client.get_collections().collections}
            missing = set(collection_names) - existing
            if not missing:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(interval_seconds)
    if last_error:
        raise RuntimeError(f"Failed to list collections: {last_error}")
    raise RuntimeError(f"Collections not available after restore: {sorted(missing)}")


def run_in_worker(
    cmd,
    cwd=None,
    user=None,
    db_mount: Path | None = None,
    extra_mounts=None,
    use_dev: bool = False,
):
    worker_service = os.getenv("RESTORE_WORKER_SERVICE", "api")
    user_flag = f"--user {user} " if user else ""
    quoted = shlex.quote(cmd)
    if not db_mount:
        raise RuntimeError("db_mount is required to run worker commands.")
    db_volume = f"-v {shlex.quote(str(db_mount))}:/app/db "
    extra = ""
    if extra_mounts:
        mounts = []
        for host_path, container_path, mode in extra_mounts:
            suffix = f":{mode}" if mode else ""
            mounts.append(
                f"-v {shlex.quote(str(host_path))}:{shlex.quote(container_path)}{suffix}"
            )
        extra = " ".join(mounts) + " "
    full_cmd = (
        f"{compose_base_command(use_dev=use_dev)} run --rm --no-deps {user_flag}"
        f"{db_volume}{extra}--entrypoint sh {worker_service} -c {quoted}"
    )
    return run_command(full_cmd, cwd=cwd)


def ensure_qdrant_payload_indexes(root_dir: Path) -> None:
    client = QdrantClient(url="http://localhost:6333")
    fields = {
        "documents_uneg": ("doc_id",),
        "chunks_uneg": ("doc_id", "sys_doc_id"),
    }
    for collection, field_names in fields.items():
        for field_name in field_names:
            try:
                client.create_payload_index(
                    collection_name=collection,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                logger.info("Created payload index on %s.%s", collection, field_name)
            except Exception:
                # Index may already exist or collection missing; ignore.
                pass


def get_latest_backup_zip(config: dict, prefix: str = "qdrant_dump_"):
    # Only if we need to download
    if not all(config.values()):
        logger.error("Missing Azure credentials to check for latest backup.")
        return None

    conn_str = (
        f"DefaultEndpointsProtocol=https;AccountName={config['account_name']};"
        f"AccountKey={config['account_key']};EndpointSuffix=core.windows.net"
    )
    client = ShareDirectoryClient.from_connection_string(
        conn_str, config["share_name"], "db/backups"
    )

    zips = []
    logger.info("Listing backups on Azure...")
    try:
        for item in client.list_directories_and_files():
            if (
                not item.is_directory
                and item.name.endswith(".zip")
                and item.name.startswith(prefix)
            ):
                zips.append(item.name)

        if not zips:
            return None
        zips.sort(reverse=True)
        return zips[0]
    except Exception as e:
        logger.error(f"Failed to list Azure files: {e}")
        return None


def download_zip(config: dict, zip_name: str, local_dir: Path):
    conn_str = (
        f"DefaultEndpointsProtocol=https;AccountName={config['account_name']};"
        f"AccountKey={config['account_key']};EndpointSuffix=core.windows.net"
    )
    client = ShareDirectoryClient.from_connection_string(
        conn_str, config["share_name"], "db/backups"
    )
    local_path = local_dir / zip_name

    logger.info(f"Downloading {zip_name}...")
    try:
        file_client = client.get_file_client(zip_name)
        with open(local_path, "wb") as data:
            stream = file_client.download_file()
            data.write(stream.readall())
        return local_path
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None


def cold_restore(
    snapshot_path: Path, project_root: Path, db_mount: Path, use_dev: bool = False
):
    """
    Performs a 'Cold Restore' of a single snapshot file.
    snapshot_path: Path to the .snapshot file on the HOST.
    """
    collection_name = resolve_collection_name(snapshot_path.stem)  # 'documents_uneg'
    logger.info(f"\n--- RESTORING COLLECTION: {collection_name} ---")

    # 1. Stop DB to release locks (if not already stopped globally)
    # We will assume DB is stopped or stop it inside main loop.

    # Paths inside container (assuming standard volume mount)
    # Host: ./db/qdrant/collections/{name} maps to Container: /app/db/qdrant/collections/{name}

    # 2. Extract specific snapshot
    # We need the snapshot accessible to the worker container.
    # We assume 'snapshot_path' is already in 'db/backups/...' or somewhere mounted.
    # If it was unzipped to a tmp dir, we should ensuring it's in the volume.

    # Let's verify where snapshot_path is relative to project root
    container_snapshot_path = None

    project_root_resolved = project_root.resolve()
    # Check 1: Is it physically inside the DB mount?
    worker_db_mount = os.getenv("RESTORE_WORKER_DB_MOUNT")
    try:
        if worker_db_mount:
            worker_mount = Path(worker_db_mount).resolve()
            rel_to_mount = snapshot_path.resolve().relative_to(worker_mount)
            container_snapshot_path = f"/app/db/{rel_to_mount}"
            logger.info(f"  Snapshot found in worker mount: {container_snapshot_path}")
        else:
            rel_to_mount = snapshot_path.resolve().relative_to(db_mount)
            # It is inside the mount!
            # container path: /app/db/... (since DB mount is mounted to /app/db)
            container_snapshot_path = f"/app/db/{rel_to_mount}"
            logger.info(f"  Snapshot found in db mount: {container_snapshot_path}")
    except ValueError:
        pass

    # Check 2: If not found yet, try project relative (standard case)
    if not container_snapshot_path:
        if db_mount.is_relative_to(project_root_resolved):
            try:
                rel_path = snapshot_path.relative_to(project_root_resolved)
                # Check if it starts with db/backups
                if str(rel_path).startswith("db/backups"):
                    container_snapshot_path = (
                        f"/app/{rel_path}"  # Worker maps '.' to '/app'
                    )
            except ValueError:
                pass

    # Check 3: Fallback - Copy to temp location
    if not container_snapshot_path:
        logger.warning(
            f"Snapshot {snapshot_path} is outside project volume ({db_mount}). Moving it..."
        )
        source_parent = snapshot_path.parent.resolve()
        staged_container_path = f"/app/db/backups/tmp_restore/{snapshot_path.name}"

        if not run_in_worker(
            "mkdir -p /app/db/backups/tmp_restore",
            cwd=project_root,
            user="0",
            db_mount=db_mount,
            use_dev=use_dev,
        ):
            return False
        if not run_in_worker(
            f"cp /restore_src/{snapshot_path.name} {staged_container_path}",
            cwd=project_root,
            user="0",
            db_mount=db_mount,
            extra_mounts=[(source_parent, "/restore_src", "ro")],
            use_dev=use_dev,
        ):
            return False

        # Now we know where it is relative to /app/db
        # (since project_root/db maps into container at /app/db)
        container_snapshot_path = staged_container_path
        logger.info(f"  Staged to: {container_snapshot_path}")

    container_target_dir = f"/app/db/qdrant/collections/{collection_name}"

    logger.info("  1. Cleaning target directory...")
    if not run_in_worker(
        f"if [ -d {container_target_dir} ]; then rm -rf {container_target_dir}; fi",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        logger.error("  Failed to remove existing collection directory.")
        return False
    if not run_in_worker(
        f"mkdir -p {container_target_dir}",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        logger.error("  Failed to recreate collection directory.")
        return False

    logger.info(f"  2. Extracting snapshot: {container_snapshot_path}")
    # This might take a while for large files
    if not run_in_worker(
        f"tar -xf {container_snapshot_path} -C {container_target_dir}",
        cwd=project_root,
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        return False

    logger.info("  3. Flattening inner segments...")
    # Run the embedded python script inside worker
    cmd = f"python -c {shlex.quote(UNPACKER_SCRIPT)} {container_target_dir}"
    if not run_in_worker(cmd, cwd=project_root, db_mount=db_mount, use_dev=use_dev):
        return False

    logger.info("  4. Fixing permissions (qdrant user 1000)...")
    # Qdrant is stopped during restore, so use worker container to chown.
    worker_target_dir = f"/app/db/qdrant/collections/{collection_name}"
    if not run_in_worker(
        f"chown -R 1000:1000 {worker_target_dir}",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        return False

    logger.info(f"  SUCCESS: {collection_name} restored on disk.")
    return True


def _resolve_delta_dir(extract_dir: Path) -> Path:
    if (extract_dir / "manifest.json").exists() and extract_dir.name.startswith(
        "qdrant_delta_"
    ):
        return extract_dir
    delta_dirs = [
        d
        for d in extract_dir.iterdir()
        if d.is_dir() and d.name.startswith("qdrant_delta_")
    ]
    if len(delta_dirs) == 1:
        return delta_dirs[0]
    raise RuntimeError("Unable to resolve delta directory from source.")


def main():
    parser = argparse.ArgumentParser(description="Cold Restore Qdrant from Backup")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use docker-compose.yml instead of docker-compose.prod.yml.",
    )
    parser.add_argument(
        "--source", "-s", help="Path to local backup (zip or directory) to restore"
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="Treat the source as a delta backup (qdrant_delta_*).",
    )
    parser.add_argument(
        "--base",
        help="Path to base dump directory for delta restores (qdrant_dump_*).",
    )
    parser.add_argument(
        "--keep", action="store_true", help="Keep downloaded/extracted files"
    )
    args = parser.parse_args()

    # scripts/sync/db -> repo root (4 levels up)
    root_dir = Path(__file__).resolve().parents[3]
    config = load_config()
    try:
        db_mount = resolve_db_mount(root_dir)
        logger.info(f"Using DB mount: {db_mount}")
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    zip_path = None
    extract_dir = None
    is_temp_download = False

    # 1. Determine Source
    if args.source:
        source_path = Path(args.source).resolve()
        if not source_path.exists():
            logger.error(f"Source not found: {source_path}")
            sys.exit(1)

        if source_path.is_dir():
            # If it's a directory (unzipped dump), use it directly.
            # We assume it contains .snapshot files.
            extract_dir = source_path
        elif source_path.suffix.lower() == ".zip":
            zip_path = source_path
        else:
            logger.info("Source is not a .zip; skipping unzip.")
            extract_dir = source_path
    else:
        logger.info("No source provided. Finding latest on Azure...")
        prefix = "qdrant_delta_" if args.delta else "qdrant_dump_"
        latest_zip = get_latest_backup_zip(config, prefix=prefix)
        if not latest_zip:
            logger.error("No backups found on Azure.")
            sys.exit(1)

        tmp_dir = root_dir / "db" / "backups" / "tmp_download"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)

        zip_path = download_zip(config, latest_zip, tmp_dir)
        if not zip_path:
            sys.exit(1)
        is_temp_download = True

    # 2. Unzip if needed
    if zip_path:
        extract_dir = zip_path.parent / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir()

        logger.info(f"Unzipping {zip_path.name}...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

    # 3. Resolve snapshots (full or delta)
    if args.delta:
        try:
            delta_dir = _resolve_delta_dir(extract_dir)
        except RuntimeError as exc:
            logger.error(str(exc))
            sys.exit(1)

        base_dir = Path(args.base).resolve() if args.base else None
        reconstructed_dir = extract_dir / (
            f"qdrant_reconstructed_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )
        try:
            apply_delta(
                delta_dir=delta_dir,
                output_dir=reconstructed_dir,
                base_dir_override=base_dir,
                xdelta3_bin="xdelta3",
            )
        except Exception as exc:
            logger.error(f"Delta apply failed: {exc}")
            sys.exit(1)
        snapshots = list(reconstructed_dir.rglob("*.snapshot"))
        extract_dir = reconstructed_dir
    else:
        # Recursively find .snapshot files
        snapshots = list(extract_dir.rglob("*.snapshot"))
        if not snapshots:
            logger.error("No .snapshot files found in source!")
            sys.exit(1)

    logger.info(f"Found snapshots: {[s.name for s in snapshots]}")

    # 4. STOP DB (Global Stop)
    logger.info("\n>>> STOPPING QDRANT SERVICE...")
    run_command(f"{compose_base_command(use_dev=args.dev)} stop qdrant", cwd=root_dir)

    # 5. Restore Each
    success_count = 0
    for snap in snapshots:
        if cold_restore(snap, root_dir, db_mount, use_dev=args.dev):
            success_count += 1

    # 6. START DB
    logger.info("\n>>> RESTARTING QDRANT SERVICE...")
    run_command(f"{compose_base_command(use_dev=args.dev)} start qdrant", cwd=root_dir)
    logger.info("Waiting for Qdrant to become ready...")
    wait_for_qdrant()
    expected_collections = [resolve_collection_name(snap.stem) for snap in snapshots]
    logger.info("Waiting for collections to load: %s", expected_collections)
    wait_for_collections(expected_collections)
    ensure_qdrant_payload_indexes(root_dir)

    # 7. Cleanup
    if is_temp_download and not args.keep:
        logger.info("Cleaning up temp files...")
        shutil.rmtree(zip_path.parent)  # removes tmp_download/

    if success_count == len(snapshots):
        logger.info(f"\nALL {success_count} COLLECTIONS RESTORED SUCCESSFULLY.")

        # Optional Verification hint
        logger.info(
            "Verification: curl http://localhost:6333/collections/documents_uneg"
        )
    else:
        logger.error("SOME RESTORES FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
