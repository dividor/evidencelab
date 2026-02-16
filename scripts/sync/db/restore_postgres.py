import argparse
import logging
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from dotenv import load_dotenv

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


def _require_value(value: str | None, name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"Missing required value: {name}")


def _resolve_dump_path(source: Path) -> Path:
    # Handle .zip files by extracting to temp directory
    if source.is_file() and source.suffix == ".zip":
        temp_dir = Path(tempfile.mkdtemp(prefix="postgres_restore_"))
        logger.info("Extracting %s to %s...", source, temp_dir)
        with zipfile.ZipFile(source, "r") as zip_ref:
            zip_ref.extractall(temp_dir)
        # Look for .dump file in extracted contents
        candidates = list(temp_dir.rglob("*.dump"))
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise RuntimeError(f"Multiple .dump files found in {source}")
        raise RuntimeError(f"No .dump file found in {source}")

    if source.is_file():
        return source
    if source.is_dir():
        candidates = list(source.glob("*.dump"))
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise RuntimeError("Multiple .dump files found; pass a single file.")
    raise RuntimeError(f"Unable to resolve Postgres dump from: {source}")


def restore_postgres(
    *,
    source: Path,
    db_name: str,
    db_user: str,
    db_password: str,
    use_dev: bool,
    clean: bool,
) -> None:
    root_dir = Path(__file__).resolve().parents[3]
    dump_path = _resolve_dump_path(source.resolve())
    if not dump_path.exists():
        raise RuntimeError(f"Dump not found: {dump_path}")

    logger.info("Restoring Postgres database from %s...", dump_path)
    clean_flag = "--clean --if-exists" if clean else ""
    cmd = (
        f"{_compose_base_command(use_dev)} exec -T "
        f"-e PGPASSWORD={db_password} postgres "
        f"pg_restore {clean_flag} -U {db_user} -d {db_name}"
    )
    with open(dump_path, "rb") as handle:
        result = subprocess.run(
            cmd, shell=True, cwd=root_dir, stdin=handle
        )  # nosec B602
    if result.returncode != 0:
        raise RuntimeError("Postgres restore failed.")


def main() -> int:
    # Load .env before parsing args so defaults work
    _load_env()

    parser = argparse.ArgumentParser(description="Restore Postgres from backup.")
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        help="Path to a .dump file, .zip archive, or directory containing a single .dump file.",
    )
    parser.add_argument(
        "--db-name",
        default=os.getenv("POSTGRES_DB"),
        help="Database name (default: POSTGRES_DB)",
    )
    parser.add_argument(
        "--db-user",
        default=os.getenv("POSTGRES_USER"),
        help="Database user (default: POSTGRES_USER)",
    )
    parser.add_argument(
        "--db-password",
        default=os.getenv("POSTGRES_PASSWORD"),
        help="Database password (default: POSTGRES_PASSWORD)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Drop objects before restore (pg_restore --clean --if-exists).",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use docker-compose.yml instead of docker-compose.prod.yml.",
    )
    args = parser.parse_args()

    try:
        db_name = _require_value(args.db_name, "POSTGRES_DB")
        db_user = _require_value(args.db_user, "POSTGRES_USER")
        db_password = _require_value(args.db_password, "POSTGRES_PASSWORD")
        restore_postgres(
            source=Path(args.source),
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            use_dev=args.dev,
            clean=args.clean,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
