import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# This python script is executed INSIDE the restore worker container
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
            os.remove(tar_path)

        except Exception as e:
            print(f"  Error unpacking {tar_path.name}: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        unpack(sys.argv[1])
"""

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> Path:
    root_dir = Path(__file__).resolve().parents[3]
    load_dotenv(root_dir / ".env")
    return root_dir


def _compose_base_command(use_dev: bool) -> str:
    if use_dev:
        return "docker compose -f docker-compose.yml"
    compose_file = os.getenv("COMPOSE_FILE", "docker-compose.prod.yml")
    return f"docker compose -f {compose_file}"


def _run_command(cmd: str, cwd=None) -> bool:
    try:
        subprocess.run(cmd, shell=True, check=True, cwd=cwd)  # nosec B602
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Command failed: %s", exc)
        return False


def _resolve_db_mount(project_root: Path) -> Path:
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
        logger.error("Failed to resolve DB mount from docker: %s", exc)

    raise RuntimeError(
        "Unable to resolve DB mount. Set DB_DATA_MOUNT or ensure qdrant is running."
    )


def _load_datasources_config(root_dir: Path) -> dict:
    config_path = root_dir / "config.json"
    if not config_path.exists():
        legacy_path = root_dir / "datasources.config.json"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            return {}
    with open(config_path, encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_collection_name(snapshot_stem: str) -> str:
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
    datasources = _load_datasources_config(root_dir).get("datasources", {})
    suffix_normalized = suffix.lower().replace(" ", "_")
    for name, details in datasources.items():
        name_slug = name.lower().replace(" ", "_")
        if suffix_normalized == name_slug:
            data_subdir = details.get("data_subdir", "").lower().replace(" ", "_")
            if data_subdir:
                return f"{prefix}{data_subdir}"
    return snapshot_stem


def _run_in_worker(
    cmd: str,
    cwd=None,
    user=None,
    db_mount: Path | None = None,
    extra_mounts=None,
    use_dev: bool = False,
) -> bool:
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
        f"{_compose_base_command(use_dev=use_dev)} run --rm --no-deps {user_flag}"
        f"{db_volume}{extra}--entrypoint sh {worker_service} -c {quoted}"
    )
    return _run_command(full_cmd, cwd=cwd)


def _cold_restore(
    snapshot_path: Path, project_root: Path, db_mount: Path, use_dev: bool = False
) -> bool:
    collection_name = _resolve_collection_name(snapshot_path.stem)
    logger.info("\n--- RESTORING COLLECTION: %s ---", collection_name)

    container_snapshot_path = None
    project_root_resolved = project_root.resolve()
    worker_db_mount = os.getenv("RESTORE_WORKER_DB_MOUNT")

    try:
        if worker_db_mount:
            worker_mount = Path(worker_db_mount).resolve()
            rel_to_mount = snapshot_path.resolve().relative_to(worker_mount)
            container_snapshot_path = f"/app/db/{rel_to_mount}"
            logger.info("  Snapshot found in worker mount: %s", container_snapshot_path)
        else:
            rel_to_mount = snapshot_path.resolve().relative_to(db_mount)
            container_snapshot_path = f"/app/db/{rel_to_mount}"
            logger.info("  Snapshot found in db mount: %s", container_snapshot_path)
    except ValueError:
        pass

    if not container_snapshot_path:
        if db_mount.is_relative_to(project_root_resolved):
            try:
                rel_path = snapshot_path.relative_to(project_root_resolved)
                if str(rel_path).startswith("db/backups"):
                    container_snapshot_path = f"/app/{rel_path}"
            except ValueError:
                pass

    if not container_snapshot_path:
        logger.warning(
            "Snapshot %s is outside project volume (%s). Moving it...",
            snapshot_path,
            db_mount,
        )
        source_parent = snapshot_path.parent.resolve()
        staged_container_path = f"/app/db/backups/tmp_restore/{snapshot_path.name}"

        if not _run_in_worker(
            "mkdir -p /app/db/backups/tmp_restore",
            cwd=project_root,
            user="0",
            db_mount=db_mount,
            use_dev=use_dev,
        ):
            return False
        if not _run_in_worker(
            f"cp /restore_src/{snapshot_path.name} {staged_container_path}",
            cwd=project_root,
            user="0",
            db_mount=db_mount,
            extra_mounts=[(source_parent, "/restore_src", "ro")],
            use_dev=use_dev,
        ):
            return False
        container_snapshot_path = staged_container_path
        logger.info("  Staged to: %s", container_snapshot_path)

    container_target_dir = f"/app/db/qdrant/collections/{collection_name}"

    logger.info("  1. Cleaning target directory...")
    if not _run_in_worker(
        f"if [ -d {container_target_dir} ]; then rm -rf {container_target_dir}; fi",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        logger.error("  Failed to remove existing collection directory.")
        return False
    if not _run_in_worker(
        f"mkdir -p {container_target_dir}",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        logger.error("  Failed to recreate collection directory.")
        return False

    logger.info("  2. Extracting snapshot: %s", container_snapshot_path)
    if not _run_in_worker(
        f"tar -xf {container_snapshot_path} -C {container_target_dir}",
        cwd=project_root,
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        return False

    logger.info("  3. Flattening inner segments...")
    cmd = f"python -c {shlex.quote(UNPACKER_SCRIPT)} {container_target_dir}"
    if not _run_in_worker(cmd, cwd=project_root, db_mount=db_mount, use_dev=use_dev):
        return False

    logger.info("  4. Fixing permissions (qdrant user 1000)...")
    if not _run_in_worker(
        f"chown -R 1000:1000 {container_target_dir}",
        cwd=project_root,
        user="0",
        db_mount=db_mount,
        use_dev=use_dev,
    ):
        return False

    logger.info("  SUCCESS: %s restored on disk.", collection_name)
    return True


def _wait_for_qdrant(timeout_seconds: int = 120, interval_seconds: int = 5) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    while time.time() < deadline:
        try:
            client = QdrantClient(url=qdrant_url)
            client.get_collections()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(interval_seconds)
    raise RuntimeError(f"Qdrant did not become ready: {last_error}")


def _wait_for_collections(
    collection_names: list[str],
    timeout_seconds: int = 300,
    interval_seconds: int = 5,
) -> None:
    deadline = time.time() + timeout_seconds
    missing = set(collection_names)
    last_error: Exception | None = None
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=qdrant_url)
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


def _ensure_payload_indexes() -> None:
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=qdrant_url)
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
                pass


def restore_qdrant(*, source: Path, use_dev: bool, skip_wait: bool) -> None:
    root_dir = _load_env()
    db_mount = _resolve_db_mount(root_dir)

    tmp_dir = None
    try:
        resolved = source.resolve()
        if resolved.suffix == ".zip":
            tmp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(resolved) as zf:
                zf.extractall(tmp_dir)
            extract_dir = Path(tmp_dir)
        elif resolved.is_dir():
            extract_dir = resolved
        else:
            raise RuntimeError(f"Source must be a .zip file or directory: {source}")

        snapshots = list(extract_dir.rglob("*.snapshot"))
        if not snapshots:
            raise RuntimeError("No .snapshot files found in source.")

        logger.info("Found snapshots: %s", [s.name for s in snapshots])

        logger.info("\n>>> STOPPING QDRANT SERVICE...")
        _run_command(f"{_compose_base_command(use_dev)} stop qdrant", cwd=root_dir)

        success_count = 0
        for snap in snapshots:
            if _cold_restore(snap, root_dir, db_mount, use_dev=use_dev):
                success_count += 1

        logger.info("\n>>> RESTARTING QDRANT SERVICE...")
        _run_command(f"{_compose_base_command(use_dev)} start qdrant", cwd=root_dir)

        if success_count < len(snapshots):
            raise RuntimeError(
                f"Restore incomplete: {success_count}/{len(snapshots)} collections restored."
            )

        if skip_wait:
            logger.info("Skipping Qdrant readiness check (--skip-wait).")
        else:
            logger.info("Waiting for Qdrant to become ready...")
            _wait_for_qdrant()
            expected = [_resolve_collection_name(s.stem) for s in snapshots]
            logger.info("Waiting for collections to load: %s", expected)
            _wait_for_collections(expected)
            _ensure_payload_indexes()

        logger.info("\nAll %d collections restored successfully.", success_count)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Restore Qdrant from backup.")
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        help="Path to a .zip backup or directory containing .snapshot files.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use docker-compose.yml instead of docker-compose.prod.yml.",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip waiting for Qdrant readiness after restore.",
    )
    args = parser.parse_args()

    try:
        restore_qdrant(
            source=Path(args.source),
            use_dev=args.dev,
            skip_wait=args.skip_wait,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
