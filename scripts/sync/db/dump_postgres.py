import argparse
import json
import logging
import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> Path:
    root_dir = Path(__file__).resolve().parents[3]
    load_dotenv(root_dir / ".env")
    return root_dir


def _compose_base_command(use_prod: bool) -> str:
    if use_prod:
        compose_file = os.getenv("COMPOSE_FILE", "docker-compose.prod.yml")
        return f"docker compose -f {compose_file}"
    return "docker compose -f docker-compose.yml"


def _resolve_output_dir(output_dir: Path, root_dir: Path) -> Path:
    if str(output_dir) == "backups":
        return root_dir / "db" / "backups"
    return output_dir


def _require_value(value: Optional[str], name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"Missing required value: {name}")


def _get_valid_data_sources(root_dir: Path) -> List[str]:
    config_path = root_dir / "config.json"
    if not config_path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    datasources = config.get("datasources", {})
    return [
        ds.get("data_subdir")
        for ds in datasources.values()
        if isinstance(ds, dict) and ds.get("data_subdir")
    ]


def _validate_dump_archive(
    *,
    root_dir: Path,
    use_prod: bool,
    dump_path: Path,
) -> None:
    """Validate that the custom-format dump can be read by pg_restore.

    This catches truncated/incomplete dumps early (e.g., broken pipe/EOF during write).
    """
    compose_cmd = _compose_base_command(use_prod)
    dump_name = dump_path.name
    # Use the postgres data dir (writable by the postgres user inside the
    # official image) rather than /tmp — avoids bandit B108 and is robust
    # against containers that mount /tmp read-only.
    container_dump_path = f"/var/lib/postgresql/data/_dump_validate_{dump_name}"

    copy_cmd = (
        f"{compose_cmd} cp {shlex.quote(str(dump_path))} "
        f"postgres:{shlex.quote(container_dump_path)}"
    )
    copy_result = subprocess.run(copy_cmd, shell=True, cwd=root_dir)  # nosec B602
    if copy_result.returncode != 0:
        raise RuntimeError(
            "Postgres dump validation failed: could not copy dump into container."
        )

    try:
        validate_cmd = (
            f"{compose_cmd} exec -T postgres "
            f"pg_restore -l {shlex.quote(container_dump_path)}"
        )
        validate_result = subprocess.run(
            validate_cmd,
            shell=True,
            cwd=root_dir,
            capture_output=True,
            text=True,
        )  # nosec B602
        if validate_result.returncode != 0:
            stderr = (validate_result.stderr or "").strip()
            raise RuntimeError(
                "Postgres dump validation failed: pg_restore could not read archive. "
                f"{stderr}"
            )
    finally:
        cleanup_cmd = (
            f"{compose_cmd} exec -T postgres "
            f"rm -f {shlex.quote(container_dump_path)}"
        )
        subprocess.run(cleanup_cmd, shell=True, cwd=root_dir)  # nosec B602


def dump_postgres(
    *,
    root_dir: Path,
    output_dir: Path,
    db_name: str,
    db_user: str,
    db_password: str,
    use_prod: bool,
    prefix: str = "",
    data_source: Optional[str] = None,
) -> Path:
    output_dir = _resolve_output_dir(output_dir, root_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{data_source}" if data_source else ""
    dir_name = f"postgres_dump_{db_name}{suffix}_{timestamp}"
    if prefix:
        dir_name = f"{prefix}{dir_name}"

    backup_dir = output_dir / dir_name
    backup_dir.mkdir(parents=True, exist_ok=True)
    dump_path = backup_dir / "postgres.dump"

    if data_source:
        table_flags = f"-t docs_{data_source} -t chunks_{data_source}"
        logger.info("Dumping tables for data source '%s'...", data_source)
    else:
        table_flags = ""
        logger.info("Dumping full Postgres database...")

    cmd = (
        f"{_compose_base_command(use_prod)} exec -T "
        f"-e PGPASSWORD={db_password} postgres "
        f"pg_dump -U {db_user} -d {db_name} -F c {table_flags}"
    ).rstrip()
    with open(dump_path, "wb") as handle:
        result = subprocess.run(
            cmd, shell=True, cwd=root_dir, stdout=handle
        )  # nosec B602
    if result.returncode != 0:
        raise RuntimeError("Postgres dump failed.")

    if dump_path.stat().st_size == 0:
        raise RuntimeError("Postgres dump is empty.")

    logger.info("Validating dump archive readability with pg_restore...")
    _validate_dump_archive(
        root_dir=root_dir,
        use_prod=use_prod,
        dump_path=dump_path,
    )

    logger.info("Backup location: %s", backup_dir)
    return backup_dir


def main() -> int:
    root_dir = _load_env()
    parser = argparse.ArgumentParser(description="Dump Postgres database to backup.")
    parser.add_argument(
        "--output",
        "-o",
        default="backups",
        help="Output directory (default: db/backups)",
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
        "--prod",
        action="store_true",
        help="Use docker-compose.prod.yml (or COMPOSE_FILE) instead of docker-compose.yml.",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Prefix to add to backup directory name.",
    )
    parser.add_argument(
        "--data-source",
        default=None,
        help="Dump only tables for this data source (e.g. wfp, uneg, worldbank).",
    )
    args = parser.parse_args()

    try:
        if args.data_source:
            valid = _get_valid_data_sources(root_dir)
            if args.data_source not in valid:
                raise RuntimeError(
                    f"Unknown data source '{args.data_source}'. "
                    f"Valid sources: {', '.join(sorted(valid))}"
                )

        db_name = _require_value(args.db_name, "POSTGRES_DB")
        db_user = _require_value(args.db_user, "POSTGRES_USER")
        db_password = _require_value(args.db_password, "POSTGRES_PASSWORD")
        dump_postgres(
            root_dir=root_dir,
            output_dir=Path(args.output),
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            use_prod=args.prod,
            prefix=args.prefix,
            data_source=args.data_source,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
