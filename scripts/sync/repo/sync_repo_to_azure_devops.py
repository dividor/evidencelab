# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv"]
# ///
"""Mirror this repository's branches (and optionally tags) to an Azure DevOps remote.

Pushes refs from a source remote (default ``origin``) to an Azure DevOps Git
repository over HTTPS. Requires only ``git`` and three values — no az CLI, no
azcopy, no Docker. All connection details come from environment variables (or
``.env``) so no credentials or repository URLs live in source control:

- ``AZURE_DEVOPS_REPO_URL``: HTTPS clone URL of the target repository, e.g.
  ``https://dev.azure.com/<org>/<project>/_git/<repo>``.
- ``AZURE_DEVOPS_USERNAME``: the account username (any non-empty value is
  accepted when the password is a personal access token; defaults to ``pat``).
- ``AZURE_DEVOPS_PASSWORD``: the password — typically a personal access token
  with Code (Read & Write) scope.

The password is injected via a git credential helper that reads the
environment at git runtime, so it never appears on a command line, in git
config, or in logs.

Usage (via uv — resolves the script's own dependencies, no project install):
    # Preview what would be pushed (no changes made)
    uv run scripts/sync/repo/sync_repo_to_azure_devops.py --branches main --dry-run

    # Sync main and a release branch, plus all tags
    uv run scripts/sync/repo/sync_repo_to_azure_devops.py \
        --branches main rc/v1.6.1 --tags
"""

import argparse
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ENV_REPO_URL = "AZURE_DEVOPS_REPO_URL"
ENV_CREDENTIAL = "AZURE_DEVOPS_PASSWORD"
ENV_USERNAME = "AZURE_DEVOPS_USERNAME"

# Shell credential helper executed by git itself. It expands the environment
# variables at git runtime — the secret never becomes part of a Python string,
# a process argument list, or any git config file.
_CREDENTIAL_HELPER = (
    '!f() { echo "username=${AZURE_DEVOPS_USERNAME:-pat}"; '
    'echo "password=${AZURE_DEVOPS_PASSWORD}"; }; f'
)


def _load_env() -> Path:
    """Load ``.env`` from the repository root and return the root path."""
    root_dir = Path(__file__).resolve().parents[3]
    load_dotenv(root_dir / ".env")
    return root_dir


def _require_env(name: str) -> str:
    """Return the value of environment variable ``name`` or fail hard."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _mask_url(url: str) -> str:
    """Return ``url`` with any userinfo section removed, safe for logging."""
    return re.sub(r"://[^/@]*@", "://", url)


def _git_env() -> Dict[str, str]:
    """Environment for git subprocesses; never prompt for credentials."""
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _run_git(args: List[str], root_dir: Path, error: str) -> None:
    """Run a git command in ``root_dir``, raising ``RuntimeError`` on failure."""
    result = subprocess.run(["git", *args], cwd=root_dir, env=_git_env())
    if result.returncode != 0:
        raise RuntimeError(error)


def _verify_branches(remote: str, branches: List[str], root_dir: Path) -> None:
    """Fail hard if any requested branch does not exist on the source remote."""
    for branch in branches:
        ref = f"refs/remotes/{remote}/{branch}"
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=root_dir,
            env=_git_env(),
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Branch '{branch}' not found on remote '{remote}' ({ref})."
            )


def _build_refspecs(remote: str, branches: List[str], tags: bool) -> List[str]:
    """Map source remote-tracking refs to target branch refs."""
    refspecs = [f"refs/remotes/{remote}/{b}:refs/heads/{b}" for b in branches]
    if tags:
        refspecs.append("refs/tags/*:refs/tags/*")
    return refspecs


def _build_push_args(
    url: str, refspecs: List[str], *, dry_run: bool, force: bool
) -> List[str]:
    """Build git arguments for the push, with credentials via helper only."""
    args = [
        "-c",
        "credential.helper=",
        "-c",
        f"credential.helper={_CREDENTIAL_HELPER}",
        "push",
    ]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    args.append(url)
    args.extend(refspecs)
    return args


def sync_to_azure_devops(
    *,
    root_dir: Path,
    remote: str,
    branches: List[str],
    tags: bool,
    dry_run: bool,
    force: bool,
) -> None:
    """Fetch the source remote and push the requested refs to Azure DevOps."""
    url = _require_env(ENV_REPO_URL)
    _require_env(ENV_CREDENTIAL)

    logger.info("Fetching latest refs from '%s'...", remote)
    _run_git(
        ["fetch", remote, "--prune", "--tags"],
        root_dir,
        f"Fetch from remote '{remote}' failed.",
    )
    _verify_branches(remote, branches, root_dir)

    refspecs = _build_refspecs(remote, branches, tags)
    mode = "[DRY RUN] " if dry_run else ""
    logger.info("%sPushing %d refspec(s) to %s", mode, len(refspecs), _mask_url(url))
    _run_git(
        _build_push_args(url, refspecs, dry_run=dry_run, force=force),
        root_dir,
        "Push to Azure DevOps failed.",
    )
    logger.info("%sSync complete.", mode)


def main() -> int:
    """CLI entry point."""
    root_dir = _load_env()
    parser = argparse.ArgumentParser(
        description="Mirror branches/tags from a source remote to Azure DevOps."
    )
    parser.add_argument(
        "--branches",
        nargs="+",
        default=["main"],
        help="Branches to sync (default: main).",
    )
    parser.add_argument(
        "--tags",
        action="store_true",
        help="Also push all tags.",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Source remote to sync from (default: origin).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be pushed without pushing anything.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force-push, overwriting diverged refs on the target.",
    )
    args = parser.parse_args()

    try:
        sync_to_azure_devops(
            root_dir=root_dir,
            remote=args.remote,
            branches=args.branches,
            tags=args.tags,
            dry_run=args.dry_run,
            force=args.force,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
