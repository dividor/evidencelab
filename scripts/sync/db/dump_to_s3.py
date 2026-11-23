"""Dump a cloud deployment's data to its transfer bucket.

Runs inside an AWS deployment as the restore task (deploy/aws/transfer.tf),
started by deploy/aws/scripts/dump-data.sh. One command:

  dump --data-source NAME --database NAME [--prefix dumps]
      Writes, under <prefix>/<UTC time>/ in the transfer bucket:
      1. postgres-<database>-<time>.sql.gz: the whole database as a plain-SQL
         export, the format restore_from_s3.py loads. Ownership and privilege
         statements are left out, as the restore leaves them out anyway.
      2. qdrant-<collection>-<time>.snapshot: a snapshot of each of the data
         source's two Qdrant collections (chunks and documents), taken through
         Qdrant's API and removed from the Qdrant server once copied.
      3. <data source>-<time>.tar: the data source's folder in /app/data
         (PDFs, parsed output, page images), links kept as links.
      4. manifest.json: each file's key, size and SHA-256, and the versions
         of Postgres, pg_dump and Qdrant that made them.

Each file is written to the task's own storage, uploaded, then deleted, so
only one is on disk at a time. Nothing in the database, Qdrant or the file
share is changed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.sync.db.restore_from_s3 import (
    DATA_ROOT,
    checked_name,
    configured_folders,
    psql_environment,
)

_CHUNK = 1024 * 1024


@dataclass
class DumpFile:
    """One file of the dump, as the manifest lists it."""

    key: str
    bytes: int
    sha256: str


def dump_stamp(now: float) -> str:
    """The dump's time, as it appears in its keys: 20261121T030500Z."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def file_sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def pg_dump_command(database: str) -> List[str]:
    """pg_dump writing DATABASE as plain SQL, without ownership or privileges."""
    return [
        "pg_dump",
        "--format=plain",
        "--no-owner",
        "--no-privileges",
        "-d",
        database,
    ]


def dump_postgres(environ: Dict[str, str], database: str, path: Path) -> None:
    """Write DATABASE to PATH as gzipped plain SQL; raise if pg_dump fails."""
    process = subprocess.Popen(
        pg_dump_command(database),
        stdout=subprocess.PIPE,
        env=psql_environment(environ),
    )
    if process.stdout is None:
        raise RuntimeError("pg_dump did not open its output")
    with gzip.open(path, "wb") as compressed:
        shutil.copyfileobj(process.stdout, compressed, _CHUNK)
    if process.wait() != 0:
        raise RuntimeError(f"pg_dump stopped with exit code {process.returncode}")


def _checked(response: Any, what: str) -> Any:
    if response.status_code != 200:
        raise RuntimeError(
            f"Qdrant refused to {what}: HTTP {response.status_code} "
            f"{response.text[:200]}"
        )
    return response


def qdrant_snapshot(
    base_url: str, api_key: str, collection: str, path: Path, http: Any
) -> None:
    """Snapshot COLLECTION through Qdrant's API into PATH, then remove it from Qdrant."""
    headers = {"api-key": api_key}
    url = f"{base_url.rstrip('/')}/collections/{collection}/snapshots"
    created = _checked(
        http.post(url, headers=headers, params={"wait": "true"}, timeout=3600),
        f"snapshot {collection}",
    )
    name = created.json()["result"]["name"]
    try:
        download = _checked(
            http.get(f"{url}/{name}", headers=headers, stream=True, timeout=3600),
            f"send the snapshot of {collection}",
        )
        with open(path, "wb") as out:
            for chunk in download.iter_content(chunk_size=_CHUNK):
                out.write(chunk)
    finally:
        _checked(
            http.delete(f"{url}/{name}", headers=headers, timeout=600),
            f"remove the snapshot of {collection}",
        )


def qdrant_version(base_url: str, api_key: str, http: Any) -> str:
    response = _checked(
        http.get(f"{base_url.rstrip('/')}/", headers={"api-key": api_key}, timeout=60),
        "say its version",
    )
    return str(response.json().get("version"))


def archive_folder(root: str, folder: str, path: Path) -> None:
    """Write ROOT/FOLDER to PATH as a tar holding FOLDER/, links kept as links."""
    source = Path(root) / folder
    if not source.is_dir():
        raise ValueError(f"{source} is not a folder on the file share")
    with tarfile.open(path, "w") as archive:
        archive.add(str(source), arcname=folder)


def command_output(command: List[str], environ: Dict[str, str]) -> str:
    result = subprocess.run(
        command, env=environ, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def check_dump_args(args: argparse.Namespace, environ: Dict[str, str]) -> str:
    """The database being dumped, once ARGS are known to be right."""
    database = checked_name(environ["POSTGRES_DB"], "POSTGRES_DB")
    if args.database != database:
        raise ValueError(
            f"--database {args.database!r} does not match this deployment's "
            f"database {database!r}: name the database you are dumping"
        )
    if args.data_source not in configured_folders():
        raise ValueError(f"{args.data_source!r} is not a data source in config.json")
    checked_name(args.data_source, "--data-source")
    return database


class Uploader:
    """Uploads each finished file under PREFIX, deletes it locally, and lists it."""

    def __init__(self, s3: Any, bucket: str, prefix: str):
        self.s3, self.bucket, self.prefix = s3, bucket, prefix
        self.files: List[DumpFile] = []

    def send(self, path: Path) -> None:
        key = f"{self.prefix}/{path.name}"
        entry = DumpFile(key=key, bytes=path.stat().st_size, sha256=file_sha256(path))
        self.s3.upload_file(str(path), self.bucket, key)
        path.unlink()
        self.files.append(entry)
        print(
            f"Wrote s3://{self.bucket}/{key} ({entry.bytes} bytes, sha256 {entry.sha256})"
        )


def dump(
    args: argparse.Namespace,
    environ: Dict[str, str],
    s3: Any,
    http: Any,
    work: Optional[Path] = None,
    now: Callable[[], float] = time.time,
) -> List[DumpFile]:
    database = check_dump_args(args, environ)
    stamp = dump_stamp(now())
    bucket = environ["TRANSFER_BUCKET"]
    uploader = Uploader(s3, bucket, f"{args.prefix.strip('/')}/{stamp}")
    qdrant_url, qdrant_key = environ["QDRANT_HOST"], environ["QDRANT_API_KEY"]
    folder = work or Path(tempfile.mkdtemp(prefix="dump-"))

    path = folder / f"postgres-{database}-{stamp}.sql.gz"
    dump_postgres(environ, database, path)
    uploader.send(path)
    for collection in (f"chunks_{args.data_source}", f"documents_{args.data_source}"):
        path = folder / f"qdrant-{collection}-{stamp}.snapshot"
        qdrant_snapshot(qdrant_url, qdrant_key, collection, path, http)
        uploader.send(path)
    path = folder / f"{args.data_source}-{stamp}.tar"
    archive_folder(DATA_ROOT, args.data_source, path)
    uploader.send(path)

    pg_env = psql_environment(environ)
    show_version = ["psql", "-X", "-tA", "-d", database, "-c", "SHOW server_version"]
    manifest = {
        "created": stamp,
        "database": database,
        "data_source": args.data_source,
        "postgres_server": command_output(show_version, pg_env),
        "pg_dump": command_output(["pg_dump", "--version"], pg_env),
        "qdrant": qdrant_version(qdrant_url, qdrant_key, http),
        "files": [asdict(f) for f in uploader.files],
    }
    key = f"{uploader.prefix}/manifest.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2).encode())
    print(f"Wrote s3://{bucket}/{key}")
    return uploader.files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "dump", help="dump the database, Qdrant and the data folder"
    )
    run.add_argument("--data-source", required=True, help="its folder name, e.g. wfp")
    run.add_argument(
        "--database",
        required=True,
        help="the database being dumped (POSTGRES_DB), as a check",
    )
    run.add_argument(
        "--prefix",
        default="dumps",
        help="folder in the transfer bucket (default: dumps)",
    )
    return parser


def main(
    argv: Optional[List[str]] = None, environ: Optional[Dict[str, str]] = None
) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    try:
        import boto3
        import requests

        dump(args, env, boto3.client("s3"), requests)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
