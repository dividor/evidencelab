import argparse
import datetime
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from azure.storage.fileshare import (
    ShareDirectoryClient,
    ShareSasPermissions,
    generate_share_sas,
)
from dotenv import load_dotenv


def get_env_vars():
    # Load .env
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    env_path = root_dir / ".env"
    load_dotenv(env_path)

    account_name = os.getenv("STORAGE_ACCOUNT_NAME")
    share_name = os.getenv("STORAGE_SHARE_NAME")
    account_key = os.getenv("STORAGE_ACCOUNT_KEY")

    if not all([account_name, share_name, account_key]):
        print(
            "Error: Missing STORAGE_ACCOUNT_NAME, STORAGE_SHARE_NAME, or "
            "STORAGE_ACCOUNT_KEY in .env"
        )
        sys.exit(1)

    return account_name, share_name, account_key


def get_share_client():
    account_name, share_name, account_key = get_env_vars()

    connection_string = (
        f"DefaultEndpointsProtocol=https;AccountName={account_name};"
        f"AccountKey={account_key};EndpointSuffix=core.windows.net"
    )
    return ShareDirectoryClient.from_connection_string(
        connection_string, share_name, directory_path=""
    )


def generate_sas_token(account_name, share_name, account_key):
    # Generate a SAS token valid for 1 hour
    sas_token = generate_share_sas(
        account_name=account_name,
        share_name=share_name,
        account_key=account_key,
        permission=ShareSasPermissions(read=True, write=True, list=True, create=True),
        expiry=datetime.datetime.utcnow() + datetime.timedelta(hours=24),
    )
    return sas_token


def run_azcopy(local_path: Path, dirs: list[str], mode: str):
    account_name, share_name, account_key = get_env_vars()
    sas_token = generate_sas_token(account_name, share_name, account_key)

    # Base Source/Dest
    remote_url_base = f"https://{account_name}.file.core.windows.net/{share_name}"

    # Set concurrency to AUTO to maximize throughput (helpful for high latency/iCloud)
    os.environ["AZCOPY_CONCURRENCY_VALUE"] = "AUTO"

    print(f"Starting AzCopy {mode}...")
    print(f"Local Root: {local_path}")
    print(f"Directories: {dirs}")

    for dir_name in dirs:
        dir_name = dir_name.strip()
        if not dir_name:
            continue

        # Ensure dir_name is treated as relative path
        dir_path_obj = Path(dir_name)
        if dir_path_obj.is_absolute():
            print(f"Warning: Absolute path {dir_name} not supported. Skipping.")
            continue

        local_dir = local_path / dir_name
        # use as_posix() for URL to ensure forward slashes
        remote_path = dir_path_obj.as_posix()
        remote_url = f"{remote_url_base}/{remote_path}?{sas_token}"

        if mode == "upload":
            if not local_dir.exists():
                print(f"Warning: Local directory {local_dir} does not exist, skipping.")
                continue
        if mode == "upload":
            if not local_dir.exists():
                print(f"Warning: Local directory {local_dir} does not exist, skipping.")
                continue
            # Sync expects direct directory paths, no wildcards
            src = str(local_dir)
            dst = remote_url
        else:  # download
            # Sync expects direct directory paths, no wildcards
            # Remove wildcard from remote URL construction
            remote_url_clean = f"{remote_url_base}/{remote_path}?{sas_token}"
            src = remote_url_clean
            dst = str(local_dir)
            # Ensure local dest exists for download
            local_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "azcopy",
            "sync",
            src,
            dst,
            "--recursive=true",
            "--exclude-regex=cache",  # Recursively exclude folders named 'cache'
            # Safety: do not delete files on destination that are missing on source
            "--delete-destination=false",
        ]
        if dir_name.lower() == "wfp":
            # Exclude only the top-level WFP folder under the wfp source.
            # Keep <year>/WFP folders intact.
            cmd.append("--exclude-path=WFP")

        print(f"\nProcessing: {dir_name}")
        print(f"  Source: {src}")
        # Mask SAS token for display if present in dest
        display_dst = dst.split("?")[0] if "?" in dst else dst
        print(f"  Dest:   {display_dst}")

        # print(" ".join(cmd)) # Debug (Careful: contains SAS token)

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running AzCopy for {dir_name}: {e}")
            sys.exit(1)
        except FileNotFoundError:
            print("Error: 'azcopy' command not found. Please install AzCopy.")
            sys.exit(1)

    print("\nAzCopy Sync Complete.")


def download_single_file(client, local_path, file_name):
    # Helper for thread pool
    print(f"  Downloading: {file_name}")
    file_client = client.get_file_client(file_name)
    with open(local_path / file_name, "wb") as data:
        stream = file_client.download_file()
        data.write(stream.readall())


def download_files_recursive(
    client: ShareDirectoryClient,
    local_path: Path,
    executor: ThreadPoolExecutor,
    is_wfp_root: bool = False,
):
    local_path.mkdir(parents=True, exist_ok=True)

    for item in client.list_directories_and_files():
        if item.name == "cache":
            continue
        if is_wfp_root and item.name == "WFP":
            continue

        if item.is_directory:
            # Recursion must happen in the main thread to discover files
            # But making directories is fast
            sub_client = client.get_subdirectory_client(item.name)
            sub_path = local_path / item.name
            sub_is_wfp_root = item.name == "wfp" and not is_wfp_root
            download_files_recursive(sub_client, sub_path, executor, sub_is_wfp_root)
        else:
            # Submit download task to pool
            executor.submit(download_single_file, client, local_path, item.name)


def download_files(client: ShareDirectoryClient, local_path: Path):
    print(f"Starting parallel download to {local_path}...")
    # Adjust max_workers as needed based on network/CPU
    with ThreadPoolExecutor(max_workers=10) as executor:
        download_files_recursive(client, local_path, executor)
    print("Download complete.")


def upload_single_file(client, file_path, file_name):
    # Helper for thread pool
    print(f"  Uploading: {file_name}")
    file_client = client.get_file_client(file_name)
    with open(file_path, "rb") as source:
        file_client.upload_file(source)


def upload_files_recursive(
    client: ShareDirectoryClient,
    local_path: Path,
    executor: ThreadPoolExecutor,
    is_wfp_root: bool = False,
):
    if not local_path.exists():
        return

    # Check remote existence to skip re-uploads
    # This listing happens in the main thread, which is safer than
    # checking existence per-file inside threads.
    existing_items = set()
    try:
        for remote_item in client.list_directories_and_files():
            existing_items.add(remote_item.name)
    except Exception:
        # Directory might not exist yet if we just created it, or other error
        # In that case assume empty
        pass

    for item in local_path.iterdir():
        if item.name == "cache":
            continue
        if is_wfp_root and item.name == "WFP":
            continue

        if item.is_dir():
            print(f"  Entering directory: {item.name}")
            sub_client = client.get_subdirectory_client(item.name)

            # Only create if it doesn't exist to save a call
            if item.name not in existing_items:
                try:
                    sub_client.create_directory()
                except Exception:
                    pass  # Directory might have been created concurrently

            sub_is_wfp_root = item.name == "wfp" and not is_wfp_root
            upload_files_recursive(sub_client, item, executor, sub_is_wfp_root)
        else:
            # File
            if item.name in existing_items:
                print(f"  Skipping existing file: {item.name}")
                continue

            # Submit upload task to pool
            executor.submit(upload_single_file, client, item, item.name)


def upload_files(client: ShareDirectoryClient, local_path: Path, dirs: list[str]):
    print(f"Starting parallel upload from {local_path}...")
    if not local_path.exists():
        print(f"Error: Local path {local_path} does not exist.")
        sys.exit(1)

    with ThreadPoolExecutor(max_workers=10) as executor:
        for dir_name in dirs:
            dir_name = dir_name.strip()
            if not dir_name:
                continue

            target_path = local_path / dir_name
            if not target_path.exists():
                print(f"Warning: Directory {target_path} does not exist, skipping.")
                continue

            print(f"Processing directory: {dir_name}")
            # Get subdirectory client for the top-level folder
            sub_client = client.get_subdirectory_client(dir_name)
            try:
                sub_client.create_directory()
            except Exception:
                pass  # Directory might already exist

            is_wfp_root = dir_name.lower() == "wfp"
            upload_files_recursive(sub_client, target_path, executor, is_wfp_root)

    print("Upload complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Sync files with Azure File Share (HTTPS) - Parallelized"
    )
    parser.add_argument(
        "--download", action="store_true", help="Download from Azure to local"
    )
    parser.add_argument(
        "--upload", action="store_true", help="Upload from local to Azure"
    )
    parser.add_argument(
        "--dirs",
        type=str,
        default="uneg,worldbank",
        help="Comma-separated list of directories to sync (default: uneg,worldbank)",
    )
    parser.add_argument(
        "--azcopy",
        action="store_true",
        help="Use AzCopy for high-performance sync (requires 'azcopy' in PATH)",
    )
    args = parser.parse_args()

    # Load .env immediately so DATA_MOUNT_PATH is available
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    env_path = root_dir / ".env"
    load_dotenv(env_path)

    if not (args.download or args.upload):
        print("Error: Must specify --download or --upload")
        parser.print_help()
        sys.exit(1)

    # Determine local sync dir
    # Prioritize DATA_MOUNT_PATH from .env if set
    data_mount_path = os.getenv("DATA_MOUNT_PATH")
    if data_mount_path:
        local_sync_dir = Path(data_mount_path)
    else:
        # Fallback to default structure
        share_name = os.getenv("STORAGE_SHARE_NAME", "evaluation-db")
        local_sync_dir = Path.home() / "mnt" / "azure" / share_name

    # Parse dirs
    dirs_to_sync = args.dirs.split(",")

    if args.azcopy:
        mode = "upload" if args.upload else "download"
        run_azcopy(local_sync_dir, dirs_to_sync, mode)
        sys.exit(0)

    client = get_share_client()

    if args.download:
        # Note: Download logic currently syncs everything except cache.
        # Use --dirs logic for download too if desired,
        # but request asked for "local folder to upload"
        download_files(client, local_sync_dir)
    elif args.upload:
        upload_files(client, local_sync_dir, dirs_to_sync)


if __name__ == "__main__":
    main()
