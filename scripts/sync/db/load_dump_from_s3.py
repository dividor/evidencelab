"""Copy a dump made by dump_to_s3.py into this deployment and load it.

Runs inside an AWS deployment as the restore task, started by
deploy/aws/scripts/restore-data.sh. copy-dump runs fetch, to bring a dump in
from another deployment's transfer bucket; load-dump runs the other three,
in this order, each given the dump's manifest.json key in this bucket:

  fetch --links KEY
      KEY is a file in this bucket holding a dump's manifest and a download
      link for each of its files, signed in the other account. Downloads each
      file to the task's own storage, checks its size and SHA-256, and only
      then uploads it under the same key; the manifest goes last.
  check --manifest KEY
      Reads every file the manifest lists and checks its size and SHA-256.
      Changes nothing.
  restore --manifest KEY --database NAME
      Loads the dump's Postgres export and folder archive, as
      restore_from_s3.py restore does.
  snapshots --manifest KEY
      Has Qdrant recover each collection from its snapshot, through a
      download link that lasts an hour; Qdrant checks the SHA-256 first.
      A collection of the same name is replaced. Refuses a dump made by
      another minor version of Qdrant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.sync.db.dump_to_s3 import _checked, qdrant_version
from scripts.sync.db.restore_from_s3 import checked_name, restore

_CHUNK = 8 * 1024 * 1024
_LINK_SECONDS = 3600


def checked_manifest(manifest: Dict[str, Any], where: str) -> Dict[str, Any]:
    """MANIFEST, once it lists files and says when and how it was made."""
    for field in ("created", "data_source", "qdrant", "files"):
        if not manifest.get(field):
            raise ValueError(f"{where} has no {field!r}: is it a dump's manifest.json?")
    return manifest


def read_manifest(s3: Any, bucket: str, key: str) -> Dict[str, Any]:
    """The manifest at KEY in BUCKET."""
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return checked_manifest(json.loads(body), key)


def _check_match(entry: Dict[str, Any], size: int, sha256: str) -> None:
    if size != entry["bytes"] or sha256 != entry["sha256"]:
        raise ValueError(
            f"{entry['key']} is {size} bytes with sha256 {sha256}; "
            f"the manifest says {entry['bytes']} bytes, {entry['sha256']}"
        )


def check_files(s3: Any, bucket: str, manifest: Dict[str, Any]) -> None:
    """Raise unless every file in MANIFEST has its listed size and SHA-256."""
    for entry in manifest["files"]:
        digest, size = hashlib.sha256(), 0
        body = s3.get_object(Bucket=bucket, Key=entry["key"])["Body"]
        for chunk in iter(lambda: body.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
        _check_match(entry, size, digest.hexdigest())
        print(f"Checked {entry['key']}: {size} bytes, sha256 matches")


def dump_folder(manifest: Dict[str, Any]) -> str:
    """The folder under dumps/ that every file in MANIFEST is in."""
    folders = {posixpath.dirname(entry["key"]) for entry in manifest["files"]}
    folder = folders.pop() if len(folders) == 1 else ""
    if not folder.startswith("dumps/") or posixpath.normpath(folder) != folder:
        raise ValueError("A dump's files must all be in one folder under dumps/")
    return folder


def fetch_file(url: str, entry: Dict[str, Any], path: Path, http: Any) -> None:
    """Download ENTRY from URL into PATH; raise unless its size and SHA-256 match."""
    response = http.get(url, stream=True, timeout=3600)
    if response.status_code != 200:
        # The link itself is a credential: it is never printed.
        raise RuntimeError(
            f"Downloading {entry['key']} failed: HTTP {response.status_code}"
        )
    digest, size = hashlib.sha256(), 0
    with open(path, "wb") as out:
        for chunk in response.iter_content(chunk_size=_CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    _check_match(entry, size, digest.hexdigest())


def fetch_dump(
    links: Dict[str, Any], bucket: str, s3: Any, http: Any, work: Optional[Path] = None
) -> str:
    """Copy the dump LINKS describes into BUCKET; return its manifest's key."""
    manifest = checked_manifest(
        links.get("manifest") or {}, "The links file's manifest"
    )
    folder = dump_folder(manifest)
    missing = [e["key"] for e in manifest["files"] if e["key"] not in links["links"]]
    if missing:
        raise ValueError(f"The links file has no link for {', '.join(missing)}")
    work = work or Path(tempfile.mkdtemp(prefix="fetch-"))
    for entry in manifest["files"]:
        path = work / posixpath.basename(entry["key"])
        fetch_file(links["links"][entry["key"]], entry, path, http)
        s3.upload_file(str(path), bucket, entry["key"])
        path.unlink()
        print(f"Copied {entry['key']}: {entry['bytes']} bytes, sha256 matches")
    key = f"{folder}/manifest.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2).encode())
    print(f"Wrote s3://{bucket}/{key}")
    return key


def restore_args(manifest: Dict[str, Any], database: str) -> argparse.Namespace:
    """restore_from_s3.py restore's arguments for the dump's export and archive."""
    keys = [entry["key"] for entry in manifest["files"]]
    archive = f"{manifest['data_source']}-{manifest['created']}.tar"
    exports = [k for k in keys if posixpath.basename(k).startswith("postgres-")]
    archives = [k for k in keys if posixpath.basename(k) == archive]
    if len(exports) != 1 or len(archives) != 1:
        raise ValueError(
            f"The manifest must list one postgres-*.sql.gz and one {archive}"
        )
    return argparse.Namespace(
        postgres_key=exports[0],
        data_key=archives[0],
        data_source=manifest["data_source"],
        database=database,
    )


def snapshot_entries(manifest: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Each (collection, file) the dump holds a Qdrant snapshot of."""
    pattern = re.compile(rf"^qdrant-(.+)-{re.escape(manifest['created'])}\.snapshot$")
    found = []
    for entry in manifest["files"]:
        match = pattern.match(posixpath.basename(entry["key"]))
        if match:
            found.append((checked_name(match.group(1), "Collection"), entry))
    if not found:
        raise ValueError("The manifest lists no Qdrant snapshots")
    return found


def same_minor(dumped: str, running: str) -> bool:
    """Whether two Qdrant versions share their major and minor numbers."""
    return dumped.split(".")[:2] == running.split(".")[:2]


def recover(
    base_url: str, api_key: str, collection: str, link: str, sha256: str, http: Any
) -> None:
    """Have Qdrant replace COLLECTION with the snapshot at LINK, checking SHA256."""
    _checked(
        http.put(
            f"{base_url.rstrip('/')}/collections/{collection}/snapshots/recover",
            headers={"api-key": api_key},
            params={"wait": "true"},
            json={"location": link, "priority": "snapshot", "checksum": sha256},
            timeout=3600,
        ),
        f"recover {collection} from its snapshot",
    )


def point_count(base_url: str, api_key: str, collection: str, http: Any) -> int:
    response = _checked(
        http.post(
            f"{base_url.rstrip('/')}/collections/{collection}/points/count",
            headers={"api-key": api_key},
            json={"exact": True},
            timeout=600,
        ),
        f"count the points in {collection}",
    )
    return int(response.json()["result"]["count"])


def load_snapshots(
    manifest: Dict[str, Any], environ: Dict[str, str], s3: Any, http: Any
) -> Dict[str, int]:
    """Recover each collection in MANIFEST into Qdrant; return its point count."""
    url, key = environ["QDRANT_HOST"], environ["QDRANT_API_KEY"]
    entries = snapshot_entries(manifest)
    running = qdrant_version(url, key, http)
    if not same_minor(manifest["qdrant"], running):
        raise ValueError(
            f"The snapshots were made by Qdrant {manifest['qdrant']}; this one runs "
            f"{running}. Load them into the same minor version."
        )
    counts = {}
    for collection, entry in entries:
        link = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": environ["TRANSFER_BUCKET"], "Key": entry["key"]},
            ExpiresIn=_LINK_SECONDS,
        )
        recover(url, key, collection, link, entry["sha256"], http)
        counts[collection] = point_count(url, key, collection, http)
        print(f"Loaded {collection} from {entry['key']}: {counts[collection]} points")
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "fetch", help="copy a dump in from another deployment's bucket"
    ).add_argument("--links", required=True)
    for name, text in (
        ("check", "check every file against the manifest"),
        ("restore", "load the Postgres export and the folder archive"),
        ("snapshots", "load the Qdrant snapshots"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--manifest", required=True)
        if name == "restore":
            command.add_argument(
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
        import boto3
        import requests
        from botocore.config import Config

        # Download links signed with Signature Version 4, not the retired 2.
        s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
        bucket = env["TRANSFER_BUCKET"]
        if args.command == "fetch":
            links = json.loads(
                s3.get_object(Bucket=bucket, Key=args.links)["Body"].read()
            )
            fetch_dump(links, bucket, s3, requests)
            return 0
        manifest = read_manifest(s3, bucket, args.manifest)
        if args.command == "check":
            check_files(s3, bucket, manifest)
        elif args.command == "restore":
            restore(restore_args(manifest, args.database), env)
        else:
            load_snapshots(manifest, env, s3, requests)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
