import argparse
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

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


def dump_postgres(
    *,
    root_dir: Path,
    output_dir: Path,
    db_name: str,
    db_user: str,
    db_password: str,
    use_prod: bool,
    prefix: str = "",
) -> Path:
    output_dir = _resolve_output_dir(output_dir, root_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_name = f"postgres_dump_{db_name}_{timestamp}"
    if prefix:
        dir_name = f"{prefix}{dir_name}"

    backup_dir = output_dir / dir_name
    backup_dir.mkdir(parents=True, exist_ok=True)
    dump_path = backup_dir / "postgres.dump"

    logger.info("Dumping Postgres database...")
    cmd = (
        f"{_compose_base_command(use_prod)} exec -T "
        f"-e PGPASSWORD={db_password} postgres "
        f"pg_dump -U {db_user} -d {db_name} -F c"
    )
    with open(dump_path, "wb") as handle:
        result = subprocess.run(
            cmd, shell=True, cwd=root_dir, stdout=handle
        )  # nosec B602
    if result.returncode != 0:
        raise RuntimeError("Postgres dump failed.")

    if dump_path.stat().st_size == 0:
        raise RuntimeError("Postgres dump is empty.")

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
    args = parser.parse_args()

    try:
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
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
