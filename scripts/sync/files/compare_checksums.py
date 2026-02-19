#!/usr/bin/env python3
"""
Compare MD5 checksums of local PDFs against Azure File Share.

Walks ./data/<source>/pdfs locally, computes MD5 for each PDF,
then streams the remote copy from Azure File Share and compares.

Usage:
    # Compare all PDFs for uneg (default)
    python scripts/sync/files/compare_checksums.py

    # Compare a specific source
    python scripts/sync/files/compare_checksums.py --source worldbank

    # Limit to first N files (useful for testing)
    python scripts/sync/files/compare_checksums.py --limit 50

    # Re-upload mismatched files
    python scripts/sync/files/compare_checksums.py --fix
"""

import argparse
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.fileshare import ShareDirectoryClient
from dotenv import load_dotenv


def get_share_client():
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(root_dir / ".env")

    account_name = os.getenv("STORAGE_ACCOUNT_NAME")
    share_name = os.getenv("STORAGE_SHARE_NAME")
    account_key = os.getenv("STORAGE_ACCOUNT_KEY")

    if not all([account_name, share_name, account_key]):
        print(
            "Error: Missing STORAGE_ACCOUNT_NAME, STORAGE_SHARE_NAME, or STORAGE_ACCOUNT_KEY"
        )
        sys.exit(1)

    connection_string = (
        f"DefaultEndpointsProtocol=https;AccountName={account_name};"
        f"AccountKey={account_key};EndpointSuffix=core.windows.net"
    )
    return ShareDirectoryClient.from_connection_string(
        connection_string, share_name, directory_path=""
    )


def md5_local(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_remote(share_client: ShareDirectoryClient, remote_path: str) -> str | None:
    try:
        file_client = share_client.get_file_client(remote_path)
        h = hashlib.md5(usedforsecurity=False)  # noqa: S324
        stream = file_client.download_file()
        for chunk in stream.chunks():
            h.update(chunk)
        return h.hexdigest()
    except ResourceNotFoundError:
        return None


def compare_one(
    share_client: ShareDirectoryClient,
    local_file: Path,
    data_root: Path,
) -> dict:
    rel_path = local_file.relative_to(data_root)
    remote_path = rel_path.as_posix()

    local_md5 = md5_local(local_file)
    remote_md5 = md5_remote(share_client, remote_path)

    local_size = local_file.stat().st_size

    if remote_md5 is None:
        return {
            "file": remote_path,
            "status": "missing_remote",
            "local_md5": local_md5,
            "remote_md5": None,
            "size": local_size,
        }
    elif local_md5 != remote_md5:
        return {
            "file": remote_path,
            "status": "mismatch",
            "local_md5": local_md5,
            "remote_md5": remote_md5,
            "size": local_size,
        }
    else:
        return {
            "file": remote_path,
            "status": "ok",
            "local_md5": local_md5,
            "remote_md5": remote_md5,
            "size": local_size,
        }


def reupload_file(
    share_client: ShareDirectoryClient,
    local_file: Path,
    remote_path: str,
) -> None:
    file_client = share_client.get_file_client(remote_path)
    with open(local_file, "rb") as f:
        file_client.upload_file(f)


def main():
    parser = argparse.ArgumentParser(description="Compare local vs Azure PDF checksums")
    parser.add_argument(
        "--source",
        default="uneg",
        help="Data source folder name (default: uneg)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit to first N files (0 = all)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Number of parallel workers (default: 6)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Re-upload mismatched files from local to remote",
    )
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(root_dir / ".env")

    data_mount = os.getenv("DATA_MOUNT_PATH")
    if data_mount:
        data_root = Path(data_mount)
    else:
        data_root = root_dir / "data"

    local_pdfs_dir = data_root / args.source / "pdfs"
    if not local_pdfs_dir.exists():
        print(f"Error: {local_pdfs_dir} does not exist")
        sys.exit(1)

    pdf_files = sorted(local_pdfs_dir.rglob("*.pdf"))
    if args.limit:
        pdf_files = pdf_files[: args.limit]

    total = len(pdf_files)
    print(f"Comparing {total} PDFs in {local_pdfs_dir} against Azure...")

    share_client = get_share_client()

    mismatches = []
    missing = []
    checked = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(compare_one, share_client, f, data_root): f
            for f in pdf_files
        }
        for future in as_completed(futures):
            checked += 1
            result = future.result()

            if result["status"] == "mismatch":
                mismatches.append(result)
                print(
                    f"  MISMATCH [{checked}/{total}] {result['file']} "
                    f"(local={result['local_md5'][:8]}.. remote={result['remote_md5'][:8]}..)"
                )
            elif result["status"] == "missing_remote":
                missing.append(result)
                print(f"  MISSING  [{checked}/{total}] {result['file']}")
            else:
                if checked % 100 == 0:
                    print(f"  OK       [{checked}/{total}]")

    print(
        f"\nResults: {checked} checked, {len(mismatches)} mismatched, {len(missing)} missing remote"
    )

    if mismatches:
        print("\nMismatched files:")
        for m in mismatches:
            print(f"  {m['file']}  (size={m['size']:,} bytes)")

    if missing:
        print(f"\nMissing on remote: {len(missing)} files")

    if args.fix and mismatches:
        print(f"\nRe-uploading {len(mismatches)} mismatched files...")
        for i, m in enumerate(mismatches, 1):
            local_file = data_root / m["file"]
            print(f"  [{i}/{len(mismatches)}] {m['file']}")
            reupload_file(share_client, local_file, m["file"])
        print("Re-upload complete.")


if __name__ == "__main__":
    main()
