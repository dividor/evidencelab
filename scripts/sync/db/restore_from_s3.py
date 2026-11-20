"""Load a Postgres export and a data archive from a cloud deployment's transfer bucket.

Runs inside an AWS deployment as the restore task (deploy/aws/transfer.tf),
started by deploy/aws/scripts/restore-data.sh, which runs the steps around it.
Two commands:

  inspect --postgres-key KEY
      Reads the export and prints what it holds: its settings, the extensions
      it creates, the roles its ownership and privilege statements name, and
      each table's row count. Changes nothing.

  restore --postgres-key KEY --data-key KEY --data-source NAME --database NAME
      1. Unpacks the data archive into /app/data. Its one top-level folder must
         be the data source's folder (for example wfp/). Links the source
         machine wrote as its own absolute paths into that folder (the pipeline
         links each parsed folder to its original file that way) are rewritten
         to point at the same file here; any other absolute link is refused.
      2. Loads the export into a new database, <database>_restore, in one
         transaction that stops at the first error. The running database is
         untouched until this has succeeded.
      3. Closes the running database to new connections, ends its open ones,
         then in one transaction renames it <database>_before_<UTC time> (kept)
         and gives the new one its name.

The export's ownership and privilege statements (ALTER ... OWNER TO, GRANT,
REVOKE, ALTER DEFAULT PRIVILEGES) are left out: they name the source server's
roles, and here every object belongs to the deployment's one database user.
The script prints how many it left out. Table data passes through as it is.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import IO, Dict, Iterable, Iterator, List, Optional

DATA_ROOT = "/app/data"
_COPY_START = re.compile(r"^COPY (\S+) .*FROM stdin;$")
_COPY_END = "\\."
_PRIVILEGES = re.compile(
    r"^(ALTER [A-Z ]+ .+ OWNER TO |GRANT |REVOKE |ALTER DEFAULT PRIVILEGES )"
)
_ROLE = re.compile(r"(?:OWNER TO|TO|FROM) (\"?[\w-]+\"?)")
_EXTENSION = re.compile(r"^CREATE EXTENSION (?:IF NOT EXISTS )?(\S+)")
_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")

# psql quotes :"name" as an identifier and :'name' as a literal, so the
# database names never become part of the SQL text.
_RECREATE_RESTORE_DB = (
    'DROP DATABASE IF EXISTS :"restore";\nCREATE DATABASE :"restore";\n'
)
_CLOSE_RUNNING_DB = (
    'ALTER DATABASE :"database" WITH ALLOW_CONNECTIONS false;\n'
    "SELECT count(pg_terminate_backend(pid)) AS ended_connections FROM pg_stat_activity\n"
    "  WHERE datname = :'database' AND pid <> pg_backend_pid();\n"
)
_SWAP = (
    'ALTER DATABASE :"database" RENAME TO :"previous";\n'
    'ALTER DATABASE :"restore" RENAME TO :"database";\n'
)


@dataclass
class ExportSummary:
    """What an export holds, as `inspect` prints it."""

    lines: int = 0
    settings: List[str] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)
    roles: Counter = field(default_factory=Counter)
    rows: Dict[str, int] = field(default_factory=dict)
    left_out: int = 0


def export_lines(stream: IO[bytes], key: str) -> Iterator[str]:
    """The export's lines, read as they stream in, gunzipped if KEY ends in .gz."""
    raw = gzip.GzipFile(fileobj=stream) if key.endswith(".gz") else stream
    yield from io.TextIOWrapper(raw, encoding="utf-8", newline="")


def without_privileges(lines: Iterable[str], summary: ExportSummary) -> Iterator[str]:
    """The lines with ownership and privilege statements left out.

    Table data between ``COPY ... FROM stdin;`` and ``\\.`` passes through
    untouched, whatever it looks like. Every line is also counted into SUMMARY.
    """
    table: Optional[str] = None
    for line in lines:
        summary.lines += 1
        text = line.rstrip("\r\n")
        if table is not None:
            if text == _COPY_END:
                table = None
            else:
                summary.rows[table] += 1
        elif copy := _COPY_START.match(text):
            table = copy.group(1)
            summary.rows[table] = 0
        elif _left_out(text, summary):
            continue
        yield line


def _left_out(text: str, summary: ExportSummary) -> bool:
    """Record what the statement TEXT tells us; True if it is left out."""
    if text.startswith("SET ") or text.startswith("SELECT pg_catalog.set_config"):
        summary.settings.append(text)
    extension = _EXTENSION.match(text)
    if extension:
        summary.extensions.append(extension.group(1).rstrip(";"))
    if _PRIVILEGES.match(text):
        summary.roles.update(r.strip('"') for r in _ROLE.findall(text))
        summary.left_out += 1
        return True
    return False


def inspect_export(lines: Iterable[str]) -> ExportSummary:
    """Read every line and return what the export holds."""
    summary = ExportSummary()
    for _ in without_privileges(lines, summary):
        pass
    return summary


def print_summary(summary: ExportSummary) -> None:
    print(f"Lines: {summary.lines}")
    print("Settings:")
    for setting in summary.settings:
        print(f"  {setting}")
    print(f"Extensions: {', '.join(summary.extensions) or 'none'}")
    roles = ", ".join(f"{r} ({n})" for r, n in summary.roles.most_common())
    print(f"Ownership and privilege statements left out: {summary.left_out}")
    print(f"  Roles they name: {roles or 'none'}")
    print(f"Tables: {len(summary.rows)}")
    for table, count in sorted(summary.rows.items()):
        print(f"  {table}: {count} rows")


def check_archive_members(
    members: Iterable[tarfile.TarInfo], folder: str
) -> Iterator[tarfile.TarInfo]:
    """Pass each member on, refusing any outside FOLDER/."""
    for member in members:
        name = member.name[2:] if member.name.startswith("./") else member.name
        if name != folder and not name.startswith(f"{folder}/"):
            raise ValueError(
                f"The data archive holds {member.name!r}, outside {folder}/: "
                f"make it with tar -C <data folder> -czf - {folder}"
            )
        yield member


def portable_link_target(member_name: str, target: str, folder: str) -> str:
    """Where a link the source machine wrote as an absolute path should point here.

    The pipeline links each parsed folder to its original file by the source
    machine's absolute path, such as ``/mnt/data/pipeline/wfp/pdfs/...``. If
    TARGET has exactly one FOLDER component and no ``..`` after it, the link is
    made relative to the member, so it points at the same file in this share.
    Anything else is refused.
    """
    parts = PurePosixPath(target).parts
    at = [i for i, part in enumerate(parts) if part == folder]
    if len(at) != 1 or ".." in parts[at[0] :]:
        raise ValueError(
            f"{member_name!r} links to {target!r}, which is not a file inside one "
            f"{folder}/ folder"
        )
    inside = PurePosixPath(*parts[at[0] :])
    name = member_name[2:] if member_name.startswith("./") else member_name
    return posixpath.relpath(str(inside), str(PurePosixPath(name).parent))


@dataclass
class ArchiveCounts:
    """What extract_archive unpacked."""

    files: int = 0
    links_rewritten: int = 0


def extract_archive(
    stream: IO[bytes], folder: str, root: str = DATA_ROOT
) -> ArchiveCounts:
    """Unpack the archive's FOLDER/ into ROOT as it streams in.

    Absolute links into FOLDER are rewritten first (portable_link_target);
    tarfile's "data" filter then refuses absolute paths, links that leave ROOT
    and device files.
    """
    counts = ArchiveCounts()

    def portable(member: tarfile.TarInfo, dest_path: str) -> Optional[tarfile.TarInfo]:
        if member.issym() and member.linkname.startswith("/"):
            target = portable_link_target(member.name, member.linkname, folder)
            member = member.replace(linkname=target, deep=False)
            counts.links_rewritten += 1
        return tarfile.data_filter(member, dest_path)

    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in check_archive_members(archive, folder):
            archive.extract(member, root, filter=portable)
            counts.files += member.isfile()
    return counts


def checked_name(name: str, what: str) -> str:
    """NAME, if it is a plain lower-case database name."""
    if not _NAME.match(name):
        raise ValueError(f"{what} {name!r} is not a plain database name")
    return name


def psql_command(
    database: str, variables: Dict[str, str], one_transaction: bool
) -> List[str]:
    """psql reading a script from its input, stopping at the first error."""
    command = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", database]
    if one_transaction:
        command.append("--single-transaction")
    for name, value in variables.items():
        command += ["-v", f"{name}={value}"]
    return command


def psql_environment(environ: Dict[str, str]) -> Dict[str, str]:
    """psql's connection settings, from the container's POSTGRES_* settings.

    PGSSLMODE and PGSSLROOTCERT come from the container as they are, so the
    database's certificate is checked.
    """
    return {
        **environ,
        "PGHOST": environ["POSTGRES_HOST"],
        "PGPORT": environ["POSTGRES_PORT"],
        "PGUSER": environ["POSTGRES_USER"],
        "PGPASSWORD": environ["POSTGRES_PASSWORD"],
    }


def run_psql(
    lines: Iterable[str],
    environ: Dict[str, str],
    database: str,
    variables: Optional[Dict[str, str]] = None,
    one_transaction: bool = False,
) -> None:
    """Feed LINES to psql against DATABASE; raise if psql reports an error."""
    process = subprocess.Popen(
        psql_command(database, variables or {}, one_transaction),
        stdin=subprocess.PIPE,
        env=psql_environment(environ),
        text=True,
        encoding="utf-8",
    )
    if process.stdin is None:
        raise RuntimeError("psql did not open its input")
    try:
        for line in lines:
            process.stdin.write(line)
        process.stdin.close()
    except BrokenPipeError:
        # psql stopped at an error and closed its input; its exit code says so.
        pass
    if process.wait() != 0:
        raise RuntimeError(f"psql stopped with exit code {process.returncode}")


def configured_folders() -> List[str]:
    """Each configured data source's folder name (its data_subdir)."""
    from pipeline.db.config import load_datasources_config

    sources = load_datasources_config().get("datasources", {})
    return [conf.get("data_subdir") or key for key, conf in sources.items()]


def s3_stream(bucket: str, key: str) -> IO[bytes]:
    import boto3

    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"]


def check_restore_args(args: argparse.Namespace, environ: Dict[str, str]) -> str:
    """The database being replaced, once ARGS are known to be right."""
    database = checked_name(environ["POSTGRES_DB"], "POSTGRES_DB")
    if args.database != database:
        raise ValueError(
            f"--database {args.database!r} does not match this deployment's "
            f"database {database!r}: name the database you are replacing"
        )
    if args.data_source not in configured_folders():
        raise ValueError(f"{args.data_source!r} is not a data source in config.json")
    return database


def restore(args: argparse.Namespace, environ: Dict[str, str]) -> None:
    database = check_restore_args(args, environ)
    names = {
        "database": database,
        "restore": f"{database}_restore",
        "previous": f"{database}_before_{time.strftime('%Y%m%d%H%M%S', time.gmtime())}",
    }
    bucket = environ["TRANSFER_BUCKET"]

    counts = extract_archive(s3_stream(bucket, args.data_key), args.data_source)
    print(
        f"Unpacked {counts.files} files into {DATA_ROOT}/{args.data_source}; "
        f"rewrote {counts.links_rewritten} absolute links to point inside it"
    )

    run_psql([_RECREATE_RESTORE_DB], environ, "postgres", names)
    summary = ExportSummary()
    lines = export_lines(s3_stream(bucket, args.postgres_key), args.postgres_key)
    run_psql(
        without_privileges(lines, summary),
        environ,
        names["restore"],
        one_transaction=True,
    )
    print(
        f"Loaded {len(summary.rows)} tables into {names['restore']}; left out "
        f"{summary.left_out} ownership and privilege statements"
    )

    run_psql([_CLOSE_RUNNING_DB], environ, "postgres", names)
    run_psql([_SWAP], environ, "postgres", names, one_transaction=True)
    print(
        f"{database} now holds the export; the previous one is kept as "
        f"{names['previous']}, closed to connections"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="print what an export holds")
    inspect.add_argument("--postgres-key", required=True)
    run = commands.add_parser("restore", help="load an export and a data archive")
    run.add_argument("--postgres-key", required=True)
    run.add_argument("--data-key", required=True)
    run.add_argument("--data-source", required=True, help="its folder name, e.g. wfp")
    run.add_argument(
        "--database",
        required=True,
        help="the database being replaced (POSTGRES_DB), as a check",
    )
    return parser


def main(
    argv: Optional[List[str]] = None, environ: Optional[Dict[str, str]] = None
) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    try:
        if args.command == "inspect":
            stream = s3_stream(env["TRANSFER_BUCKET"], args.postgres_key)
            print_summary(inspect_export(export_lines(stream, args.postgres_key)))
        else:
            restore(args, env)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
