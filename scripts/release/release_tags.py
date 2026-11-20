"""Image tags, release notes and release titles for Evidence Lab's releases.

The Publish images workflow (.github/workflows/publish-images.yml) calls this
script, so the rules for what gets published under which name live in one
tested place:

- A merge to ``main`` (or a push to a ``release-X.Y`` patch branch) builds the
  image once. It is published as ``sha-<7 characters of the commit>``, which
  never moves, and as the branch name, which moves to the newest commit.
- A release tag on a commit adds names to that commit's image without
  rebuilding it: ``vX.Y.Z-rc.N`` adds ``X.Y.Z-rc.N``; ``vX.Y.Z`` adds
  ``X.Y.Z``, plus ``X.Y`` and ``latest`` when it is the newest release of its
  line and overall.
- Both kinds of tag need the release's ``CHANGELOG.md`` entry at the tagged
  commit, because the release is tagged on the candidate's own commit.
- A ``vX.Y.Z`` tag becomes a GitHub release titled from the tag's message, with
  the version's ``CHANGELOG.md`` entry as its notes.

Usage:
  release_tags.py branch-tags --branch main --sha <commit> --head <branch head>
  release_tags.py source-tag --sha <commit>
  release_tags.py version-tags --tag vX.Y.Z --existing <file of tag names>
  release_tags.py is-release --tag vX.Y.Z
  release_tags.py release-notes --tag vX.Y.Z --changelog CHANGELOG.md
  release_tags.py release-title --tag vX.Y.Z --tag-type tag --subject "<headline>"

Each command prints its result, one item per line, and exits non-zero with a
message on anything it cannot accept.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

_VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
_PATCH_BRANCH = re.compile(r"^release-\d+\.\d+$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_SHORT_SHA = 7


@dataclass(frozen=True)
class Version:
    """A release version: ``X.Y.Z``, or a candidate ``X.Y.Z-rc.N``."""

    major: int
    minor: int
    patch: int
    rc: Optional[int] = None

    @property
    def is_candidate(self) -> bool:
        return self.rc is not None

    @property
    def line(self) -> str:
        return f"{self.major}.{self.minor}"

    @property
    def number(self) -> str:
        """The version without the leading ``v``: ``1.6.7`` or ``1.6.7-rc.1``."""
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.rc is None else f"{base}-rc.{self.rc}"

    def sort_key(self) -> tuple:
        # A release sorts after all of its candidates.
        return (self.major, self.minor, self.patch, self.rc is None, self.rc or 0)


def parse_version_tag(tag: str) -> Version:
    """Parse ``vX.Y.Z`` or ``vX.Y.Z-rc.N``; anything else is refused."""
    match = _VERSION_TAG.match(tag)
    if not match:
        raise ValueError(
            f"{tag!r} is not a release tag: use vX.Y.Z for a release or "
            "vX.Y.Z-rc.N for a release candidate"
        )
    major, minor, patch, rc = match.groups()
    return Version(int(major), int(minor), int(patch), int(rc) if rc else None)


def source_tag(sha: str) -> str:
    """The image name that never moves for a commit: ``sha-<7 characters>``."""
    if not _COMMIT.match(sha):
        raise ValueError(f"{sha!r} is not a git commit hash")
    return f"sha-{sha[:_SHORT_SHA]}"


def branch_image_tags(branch: str, sha: str, head: str) -> List[str]:
    """Names for an image built from a push to ``main`` or a patch branch.

    ``head`` is the branch's newest commit when publishing. The branch name
    moves only while ``sha`` is still the head, so a slower build of an older
    commit never moves it backwards.
    """
    if branch != "main" and not _PATCH_BRANCH.match(branch):
        raise ValueError(
            f"Images are published from main and release-X.Y patch branches only, "
            f"not {branch!r}"
        )
    tags = [source_tag(sha)]
    if head == sha:
        tags.insert(0, branch)
    return tags


def _release_versions(tag_names: Iterable[str]) -> List[Version]:
    """The releases (not candidates) among git tag names.

    Accepts plain names (``v1.6.5``) or ``git ls-remote`` lines
    (``<sha>\\trefs/tags/v1.6.5``). Tags that are not release tags are not
    releases, so they are left out.
    """
    versions = []
    for line in tag_names:
        line = line.strip()
        if not line:
            continue
        name = line.split()[-1].removeprefix("refs/tags/")
        if _VERSION_TAG.match(name):
            version = parse_version_tag(name)
            if not version.is_candidate:
                versions.append(version)
    return versions


def version_image_tags(tag: str, existing_tags: Iterable[str]) -> List[str]:
    """Names a release tag adds to its commit's image.

    ``existing_tags`` are the repository's tags, including ``tag`` itself.
    ``X.Y`` moves only to the newest patch of its line, and ``latest`` only to
    the newest release, so tagging a patch for an older line moves neither.
    """
    version = parse_version_tag(tag)
    if version.is_candidate:
        return [version.number]
    releases = _release_versions(existing_tags) + [version]
    newest = max(releases, key=Version.sort_key)
    newest_in_line = max(
        (v for v in releases if v.line == version.line), key=Version.sort_key
    )
    tags = [version.number]
    if version.sort_key() >= newest_in_line.sort_key():
        tags.append(version.line)
    if version.sort_key() >= newest.sort_key():
        tags.append("latest")
    return tags


def release_notes(changelog: str, tag: str) -> str:
    """The release's ``CHANGELOG.md`` entry, from its ``## [X.Y.Z]`` heading.

    A candidate ``vX.Y.Z-rc.N`` needs the entry for ``X.Y.Z`` too: the release
    is tagged on the candidate's own commit, so the entry must already be there.
    """
    version = parse_version_tag(tag)
    release = f"{version.major}.{version.minor}.{version.patch}"
    heading = re.compile(rf"^## \[{re.escape(release)}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$")
    lines = changelog.splitlines()
    start = next((i for i, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        raise ValueError(
            f"CHANGELOG.md has no '## [{release}] - YYYY-MM-DD' entry at this "
            "commit: merge the changelog entry before tagging"
        )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")),
        len(lines),
    )
    entry = "\n".join(lines[start:end]).strip()
    if entry == lines[start].strip():
        raise ValueError(f"The CHANGELOG.md entry for {release} is empty")
    return entry + "\n"


def release_title(tag: str, tag_type: str, subject: str) -> str:
    """``Evidence Lab vX.Y.Z — <headline>``, the headline being the tag's message.

    ``tag_type`` is git's object type for the tag: ``tag`` for an annotated tag,
    ``commit`` for a lightweight one, which has no message and is refused.
    """
    version = parse_version_tag(tag)
    if version.is_candidate:
        raise ValueError(
            f"{tag} is a release candidate: candidates get no GitHub release"
        )
    if tag_type != "tag":
        raise ValueError(
            f"{tag} has no message: release with an annotated tag whose message is "
            f'the headline, for example: git tag -a {tag} -m "<headline>"'
        )
    headline = subject.strip()
    if not headline:
        raise ValueError(f"{tag}'s message is empty: it is the release's headline")
    return f"Evidence Lab {tag} — {headline}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    branch = commands.add_parser("branch-tags", help="names for a branch build")
    branch.add_argument("--branch", required=True)
    branch.add_argument("--sha", required=True)
    branch.add_argument("--head", required=True, help="the branch's newest commit")

    source = commands.add_parser(
        "source-tag", help="the fixed name for a commit's image"
    )
    source.add_argument("--sha", required=True)

    version = commands.add_parser("version-tags", help="names a release tag adds")
    version.add_argument("--tag", required=True)
    version.add_argument(
        "--existing",
        required=True,
        type=Path,
        help="file of the repository's tag names, one per line",
    )

    is_release = commands.add_parser(
        "is-release", help="true for vX.Y.Z, false for a candidate"
    )
    is_release.add_argument("--tag", required=True)

    notes = commands.add_parser("release-notes", help="the version's changelog entry")
    notes.add_argument("--tag", required=True)
    notes.add_argument("--changelog", required=True, type=Path)

    title = commands.add_parser("release-title", help="the GitHub release title")
    title.add_argument("--tag", required=True)
    title.add_argument("--tag-type", required=True)
    title.add_argument("--subject", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "branch-tags":
            output = "\n".join(branch_image_tags(args.branch, args.sha, args.head))
        elif args.command == "source-tag":
            output = source_tag(args.sha)
        elif args.command == "version-tags":
            existing = args.existing.read_text().splitlines()
            output = "\n".join(version_image_tags(args.tag, existing))
        elif args.command == "is-release":
            output = "false" if parse_version_tag(args.tag).is_candidate else "true"
        elif args.command == "release-notes":
            output = release_notes(args.changelog.read_text(), args.tag).rstrip("\n")
        else:
            output = release_title(args.tag, args.tag_type, args.subject)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
