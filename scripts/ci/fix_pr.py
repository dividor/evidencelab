"""Open a fix pull request for what a review check found on a pull request.

When the docs check or the UX review finds problems on a pull request, CI asks
a model to fix exactly those findings in a checkout of the pull request's
branch. This script then puts the edits on a new branch and opens a pull
request into the reviewed pull request's branch, for its author to review and
merge (their pull request's checks then run again):

- Edits outside the check's area are refused, and no pull request is opened:
  ``docs/`` for the docs check, ``ui/frontend/src/`` for the UX review.
- An older fix pull request from the same check, on the same pull request, is
  closed first, so there is one at a time.
- When the model changed nothing, nothing is opened.

Usage (in the workflow, with the details in the environment):
  fix_pr.py docs
  fix_pr.py ux

Environment:
  PR        the reviewed pull request's number
  HEAD_REF  its branch, which the fix pull request goes into
  SHA       its head commit
  REPO      owner/name
  RUN_URL   the workflow run
  VERDICT   the check's structured verdict (JSON)
  GH_TOKEN  a token that may push branches and open pull requests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

Runner = Callable[..., subprocess.CompletedProcess]

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
NOT_PERMITTED = "not permitted to create or approve pull requests"
PERMISSION_HELP = (
    "GitHub Actions may not open pull requests in this repository. To allow it, "
    "turn on Settings > Actions > General > Workflow permissions > "
    '"Allow GitHub Actions to create and approve pull requests".'
)


@dataclass(frozen=True)
class FixKind:
    """What a check's fix pull request may change, and how it is named."""

    check: str
    paths: tuple[str, ...]
    branch: str
    title: str


KINDS = {
    "docs": FixKind(
        check="docs check",
        paths=("docs/",),
        branch="docs-fix/pr-{pr}-{sha}",
        title="docs: add the docs the docs check found missing in #{pr}",
    ),
    "ux": FixKind(
        check="UX review",
        paths=("ui/frontend/src/",),
        branch="ux-fix/pr-{pr}-{sha}",
        title="fix(ui): address the UX review of #{pr}",
    ),
}


def run_cmd(args: list[str], run: Runner, stdin: Optional[str] = None) -> str:
    """Run a command; raise with its error output when it fails."""
    result = run(args, input=stdin, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def changed_paths(run: Runner) -> list[str]:
    """Every file the model added, changed or deleted in the checkout."""
    out = run_cmd(["git", "status", "--porcelain", "--untracked-files=all"], run)
    paths = []
    for line in out.splitlines():
        entry = line[3:]
        # A rename is shown as "old -> new": both sides count.
        paths.extend(part.strip() for part in entry.split(" -> "))
    return paths


def outside(paths: list[str], allowed: tuple[str, ...]) -> list[str]:
    """The PATHS that are not under any of the ALLOWED folders."""
    return [path for path in paths if not path.startswith(allowed)]


def findings_lines(kind: str, verdict: dict[str, Any]) -> list[str]:
    """The check's findings, one Markdown line each."""
    if kind == "docs":
        return [f"- **{item['where']}**: {item['what']}" for item in verdict["missing"]]
    return [
        f"- **{item['severity']}**, {item['where']}: {item['what']}"
        for item in verdict["findings"]
    ]


def fix_body(kind: str, verdict: dict[str, Any], pr: str, run_url: str) -> str:
    """The fix pull request's description."""
    spec = KINDS[kind]
    return "\n".join(
        [
            f"The {spec.check} found these problems in #{pr}, and this pull request "
            "fixes them. It was written by a model from the findings alone, so "
            f"review it before merging it into #{pr}'s branch; #{pr}'s checks then "
            "run again.",
            "",
            *findings_lines(kind, verdict),
            "",
            f"Only files under {', '.join(f'`{p}`' for p in spec.paths)} were changed. "
            f"[Run]({run_url})",
        ]
    )


def older_fix_prs(kind: str, pr: str, repo: str, run: Runner) -> list[int]:
    """Open fix pull requests from the same check for the same pull request."""
    prefix = KINDS[kind].branch.format(pr=pr, sha="")
    listing = run_cmd(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "number,headRefName",
            "--limit",
            "100",
        ],
        run,
    )
    return [
        int(item["number"])
        for item in json.loads(listing)
        if item["headRefName"].startswith(prefix)
    ]


def open_fix_pr(kind: str, env: dict[str, str], run: Runner = subprocess.run) -> int:
    """Put the model's edits on a branch and open the fix pull request.

    Returns 0 when it opened one or there was nothing to fix, 1 when the edits
    went outside the check's area or GitHub refused the pull request.
    """
    spec = KINDS[kind]
    pr, head, repo = env["PR"], env["HEAD_REF"], env["REPO"]
    paths = changed_paths(run)
    if not paths:
        print(f"The {spec.check} fix changed nothing; no pull request opened.")
        return 0
    stray = outside(paths, spec.paths)
    if stray:
        print(
            f"The {spec.check} fix changed files outside {', '.join(spec.paths)}, so no "
            f"pull request was opened: {', '.join(stray)}",
            file=sys.stderr,
        )
        return 1
    verdict = json.loads(env["VERDICT"])
    branch = spec.branch.format(pr=pr, sha=env["SHA"][:7])
    title = spec.title.format(pr=pr)
    for number in older_fix_prs(kind, pr, repo, run):
        run_cmd(
            [
                "gh",
                "pr",
                "close",
                str(number),
                "--repo",
                repo,
                "--delete-branch",
                "--comment",
                f"Replaced by a newer {spec.check} fix for #{pr}.",
            ],
            run,
        )
    run_cmd(["git", "checkout", "-b", branch], run)
    run_cmd(["git", "add", "-A", "--", *spec.paths], run)
    run_cmd(
        [
            "git",
            "-c",
            f"user.name={BOT_NAME}",
            "-c",
            f"user.email={BOT_EMAIL}",
            "commit",
            "-m",
            title,
        ],
        run,
    )
    run_cmd(["git", "push", "origin", branch], run)
    body = fix_body(kind, verdict, pr, env["RUN_URL"])
    command = ["gh", "pr", "create", "--repo", repo, "--base", head, "--head", branch]
    try:
        url = run_cmd([*command, "--title", title, "--body-file", "-"], run, stdin=body)
    except RuntimeError as exc:
        if NOT_PERMITTED in str(exc):
            print(PERMISSION_HELP, file=sys.stderr)
            return 1
        raise
    print(f"Opened {url.strip()} into {head}.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in KINDS:
        print("usage: fix_pr.py docs|ux", file=sys.stderr)
        return 2
    return open_fix_pr(argv[0], dict(os.environ))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
