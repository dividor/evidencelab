"""Post a pull request check's verdict as one comment, and report pass or fail.

Two checks ask a model to follow a checklist and answer with a fixed JSON
verdict:

- docs: the docs check (.github/workflows/docs-check.yml) follows
  .github/review/docs-check.md. This script posts its verdict as one comment on
  the pull request, updated in place on every push, and exits non-zero when
  docs are missing, so that workflow's check shows red.
- ux: the UX review in CI's integration-tests job follows
  .github/review/ux-review.md. This script posts its findings as one comment
  and reports a separate "UX review" check, which passes only when the verdict
  is "looks good". It always exits 0 when it has reported, so the review never
  fails the integration tests.

A missing or malformed verdict counts as failed: a check that gave no answer
has not passed.

Usage (in the workflow, with the verdict and pull request in the environment):
  review_comment.py docs
  review_comment.py ux

Environment:
  VERDICT  the action's structured_output, a JSON object
  REPO     owner/name
  PR       pull request number
  SHA      the pull request's head commit
  RUN_URL  the workflow run, linked from the comment
  REVIEW_OUTCOME  ux only: the review step's outcome, quoted when it gave no
           verdict (for example "skipped" when its tool did not install)
  GH_TOKEN a token that may comment on pull requests and, for ux, create
           check runs (read by the gh CLI)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable, Optional

DOCS_MARKER = "<!-- docs-check -->"
DOCS_FIELDS = ("needs_docs", "covered", "reason", "missing", "notes")
UX_MARKER = "<!-- ux-review -->"
UX_FIELDS = ("verdict", "summary", "screens", "findings")
UX_CHECK_NAME = "UX review"
UX_PASS = "looks good"
COMMENT_AUTHOR = "github-actions[bot]"
# GitHub's limit on a check run's summary.
CHECK_SUMMARY_LIMIT = 65535

Runner = Callable[..., subprocess.CompletedProcess]


def parse_verdict(raw: Optional[str], fields: tuple[str, ...]) -> dict[str, Any]:
    """The verdict RAW holds; ValueError when it is empty, not JSON or lacks FIELDS."""
    if not raw or not raw.strip():
        raise ValueError("the check gave no verdict")
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the verdict is not JSON: {exc}") from exc
    if not isinstance(verdict, dict):
        raise ValueError("the verdict is not a JSON object")
    absent = [name for name in fields if name not in verdict]
    if absent:
        raise ValueError(f"the verdict lacks {', '.join(absent)}")
    return verdict


def docs_failed(verdict: dict[str, Any]) -> bool:
    """True when the change needs docs that it does not include."""
    return bool(verdict["needs_docs"]) and not bool(verdict["covered"])


def docs_headline(verdict: dict[str, Any]) -> str:
    if not verdict["needs_docs"]:
        return "passed: no docs needed"
    if verdict["covered"]:
        return "passed: the docs are included"
    return "failed: docs are missing"


def docs_comment(verdict: dict[str, Any], sha: str, run_url: str) -> str:
    """The pull request comment for a docs check VERDICT on commit SHA."""
    lines = [
        DOCS_MARKER,
        f"### Docs check {docs_headline(verdict)}",
        "",
        verdict["reason"],
    ]
    if verdict["missing"]:
        lines += ["", "**Missing from `docs/`**"]
        lines += [
            f"- **{item['where']}**: {item['what']}" for item in verdict["missing"]
        ]
    if verdict["notes"]:
        lines += ["", "**Worth a look** (doesn't block)"]
        lines += [f"- {note}" for note in verdict["notes"]]
    lines += [
        "",
        f"<sub>Commit {sha[:7]}, checked against `.github/review/docs-check.md`. "
        f"[Run]({run_url})</sub>",
    ]
    return "\n".join(lines)


def ux_failed(verdict: dict[str, Any]) -> bool:
    """True unless the review looked and found nothing that must change."""
    return verdict["verdict"] != UX_PASS


def table_cell(text: Any) -> str:
    """TEXT as one Markdown table cell: no line breaks, pipes escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


def ux_comment(verdict: dict[str, Any], sha: str, run_url: str) -> str:
    """The pull request comment for a UX review VERDICT on commit SHA."""
    lines = [UX_MARKER, f"### UX review: {verdict['verdict']}", "", verdict["summary"]]
    if verdict["findings"]:
        lines += [
            "",
            "| Severity | Where | What | Suggested fix |",
            "|---|---|---|---|",
        ]
        lines += [
            "| "
            + " | ".join(
                table_cell(item[key]) for key in ("severity", "where", "what", "fix")
            )
            + " |"
            for item in verdict["findings"]
        ]
    if verdict["screens"]:
        lines += ["", "<details><summary>Screens reviewed</summary>", ""]
        lines += [f"- {screen}" for screen in verdict["screens"]]
        lines += ["", "</details>"]
    lines += [
        "",
        f"<sub>Commit {sha[:7]}, reviewed against `.github/review/ux-review.md`. "
        f"The screenshots are in the run's `ux-review-screenshots` artifact. "
        f"[Run]({run_url})</sub>",
    ]
    return "\n".join(lines)


def no_verdict_comment(
    marker: str, title: str, error: str, sha: str, run_url: str
) -> str:
    """The comment when a check gave no usable verdict."""
    return "\n".join(
        [
            marker,
            f"### {title} failed: no verdict",
            "",
            f"The check ran but {error}. See the [run]({run_url}).",
            "",
            f"<sub>Commit {sha[:7]}.</sub>",
        ]
    )


def find_comment_id(pages: list[list[dict[str, Any]]], marker: str) -> Optional[int]:
    """The id of this workflow's earlier comment carrying MARKER, if any."""
    for page in pages:
        for comment in page:
            author = (comment.get("user") or {}).get("login")
            body = comment.get("body") or ""
            if author == COMMENT_AUTHOR and body.startswith(marker):
                return int(comment["id"])
    return None


def gh_api(
    args: list[str], run: Runner = subprocess.run, body: Optional[str] = None
) -> str:
    """Call the GitHub API through the gh CLI; raise when it fails."""
    result = run(
        ["gh", "api", *args],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def upsert_comment(
    repo: str, pr: str, marker: str, body: str, run: Runner = subprocess.run
) -> None:
    """Update this workflow's comment carrying MARKER on the pull request, or add it."""
    listing = gh_api(
        ["--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments"], run=run
    )
    existing = find_comment_id(json.loads(listing), marker)
    payload = json.dumps({"body": body})
    if existing is None:
        gh_api(
            ["-X", "POST", f"repos/{repo}/issues/{pr}/comments", "--input", "-"],
            run=run,
            body=payload,
        )
    else:
        gh_api(
            ["-X", "PATCH", f"repos/{repo}/issues/comments/{existing}", "--input", "-"],
            run=run,
            body=payload,
        )


def report_check(
    repo: str,
    sha: str,
    failed: bool,
    title: str,
    summary: str,
    run: Runner = subprocess.run,
) -> None:
    """Report the UX review on commit SHA as its own completed check."""
    payload = {
        "name": UX_CHECK_NAME,
        "head_sha": sha,
        "status": "completed",
        "conclusion": "failure" if failed else "success",
        "output": {"title": title, "summary": summary[:CHECK_SUMMARY_LIMIT]},
    }
    gh_api(
        ["-X", "POST", f"repos/{repo}/check-runs", "--input", "-"],
        run=run,
        body=json.dumps(payload),
    )


def run_docs(env: dict[str, str], run: Runner = subprocess.run) -> int:
    """Post the docs check's verdict; 1 when it failed or gave none, else 0."""
    repo, pr, sha, run_url = env["REPO"], env["PR"], env["SHA"], env["RUN_URL"]
    try:
        verdict = parse_verdict(env.get("VERDICT"), DOCS_FIELDS)
    except ValueError as exc:
        body = no_verdict_comment(DOCS_MARKER, "Docs check", str(exc), sha, run_url)
        upsert_comment(repo, pr, DOCS_MARKER, body, run=run)
        print(f"Docs check: {exc}", file=sys.stderr)
        return 1
    upsert_comment(repo, pr, DOCS_MARKER, docs_comment(verdict, sha, run_url), run=run)
    failed = docs_failed(verdict)
    print(f"Docs check {docs_headline(verdict)}: {verdict['reason']}")
    return 1 if failed else 0


def run_ux(env: dict[str, str], run: Runner = subprocess.run) -> int:
    """Post the UX review's findings and report its check; 0 once reported."""
    repo, pr, sha, run_url = env["REPO"], env["PR"], env["SHA"], env["RUN_URL"]
    try:
        verdict = parse_verdict(env.get("VERDICT"), UX_FIELDS)
    except ValueError as exc:
        error = str(exc)
        if env.get("REVIEW_OUTCOME"):
            error += f" (the review step's outcome was {env['REVIEW_OUTCOME']})"
        body = no_verdict_comment(UX_MARKER, "UX review", error, sha, run_url)
        upsert_comment(repo, pr, UX_MARKER, body, run=run)
        report_check(repo, sha, True, "No verdict", body, run=run)
        print(f"UX review: {exc}", file=sys.stderr)
        return 0
    body = ux_comment(verdict, sha, run_url)
    upsert_comment(repo, pr, UX_MARKER, body, run=run)
    report_check(
        repo, sha, ux_failed(verdict), f"UX review: {verdict['verdict']}", body, run=run
    )
    print(f"UX review: {verdict['verdict']}: {verdict['summary']}")
    return 0


COMMANDS = {"docs": run_docs, "ux": run_ux}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print("usage: review_comment.py docs|ux", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](dict(os.environ))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
