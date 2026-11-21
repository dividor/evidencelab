"""Tests for scripts/release/release_tags.py: image tags, release notes and titles."""

import json

import pytest

import scripts.release.release_tags as rt

pytestmark = pytest.mark.unit

# Full-length commit hashes: a 7-character prefix padded to git's 40.
SHA = "3db0bba" + "0" * 33
OLDER_SHA = "937ce0e" + "1" * 33

CHANGELOG = """# Changelog

All notable changes.

## [1.6.6] - 2026-11-21

Evidence Lab v1.6.6 adds Amazon Rerank.

### Search
- Reranked with Amazon Rerank (#624)

## [1.6.5] - 2026-11-05

Packaging release.
"""


class TestParseVersionTag:
    def test_parse_version_tag_when_release_then_no_candidate(self):
        version = rt.parse_version_tag("v1.6.7")
        assert (version.major, version.minor, version.patch, version.rc) == (
            1,
            6,
            7,
            None,
        )
        assert version.number == "1.6.7"
        assert not version.is_candidate

    def test_parse_version_tag_when_candidate_then_rc_number(self):
        version = rt.parse_version_tag("v1.6.7-rc.2")
        assert version.rc == 2
        assert version.number == "1.6.7-rc.2"
        assert version.is_candidate

    @pytest.mark.parametrize(
        "tag",
        ["1.6.7", "v1.6", "v1.6.7-rc", "v1.6.7-beta.1", "rc-v1.6.6", "v1.6.7 ", ""],
    )
    def test_parse_version_tag_when_not_release_tag_then_refused(self, tag):
        with pytest.raises(ValueError, match="not a release tag"):
            rt.parse_version_tag(tag)

    def test_sort_key_when_release_and_candidate_then_release_is_newer(self):
        release = rt.parse_version_tag("v1.6.7")
        candidate = rt.parse_version_tag("v1.6.7-rc.9")
        assert release.sort_key() > candidate.sort_key()
        assert rt.parse_version_tag("v1.10.0").sort_key() > release.sort_key()


class TestSourceTag:
    def test_source_tag_when_full_sha_then_seven_characters(self):
        assert rt.source_tag(SHA) == "sha-3db0bba"

    @pytest.mark.parametrize("sha", ["", "3db0bb", "main", "3DB0BBA240", "g" * 40])
    def test_source_tag_when_not_commit_hash_then_refused(self, sha):
        with pytest.raises(ValueError, match="not a git commit hash"):
            rt.source_tag(sha)


class TestBranchImageTags:
    def test_branch_image_tags_when_main_head_then_moving_and_fixed_names(self):
        assert rt.branch_image_tags("main", SHA, SHA) == ["main", "sha-3db0bba"]

    def test_branch_image_tags_when_main_moved_on_then_fixed_name_only(self):
        assert rt.branch_image_tags("main", OLDER_SHA, SHA) == ["sha-937ce0e"]

    def test_branch_image_tags_when_patch_branch_then_branch_name(self):
        assert rt.branch_image_tags("release-1.6", SHA, SHA) == [
            "release-1.6",
            "sha-3db0bba",
        ]

    @pytest.mark.parametrize(
        "branch", ["rc/v1.6.6", "feat/x", "release/v1.6.6", "release-1"]
    )
    def test_branch_image_tags_when_other_branch_then_refused(self, branch):
        with pytest.raises(ValueError, match="main and release-X.Y"):
            rt.branch_image_tags(branch, SHA, SHA)


class TestVersionImageTags:
    EXISTING = ["v1.6.4", "v1.6.5", "v1.5.2", "v1.6.6-rc.1", "not-a-release"]

    def test_version_image_tags_when_candidate_then_candidate_name_only(self):
        assert rt.version_image_tags("v1.6.6-rc.2", self.EXISTING) == ["1.6.6-rc.2"]

    def test_version_image_tags_when_newest_release_then_line_and_latest(self):
        existing = self.EXISTING + ["v1.6.6"]
        assert rt.version_image_tags("v1.6.6", existing) == ["1.6.6", "1.6", "latest"]

    def test_version_image_tags_when_tag_not_yet_listed_then_same_result(self):
        assert rt.version_image_tags("v1.6.6", self.EXISTING) == [
            "1.6.6",
            "1.6",
            "latest",
        ]

    def test_version_image_tags_when_patch_for_older_line_then_line_only(self):
        assert rt.version_image_tags("v1.5.3", self.EXISTING) == ["1.5.3", "1.5"]

    def test_version_image_tags_when_older_patch_of_same_line_then_exact_only(self):
        assert rt.version_image_tags("v1.6.3", self.EXISTING) == ["1.6.3"]

    def test_version_image_tags_when_ls_remote_lines_then_tag_names_read(self):
        existing = [f"{SHA}\trefs/tags/v1.7.0", f"{OLDER_SHA}\trefs/tags/v1.6.5", ""]
        assert rt.version_image_tags("v1.6.6", existing) == ["1.6.6", "1.6"]

    def test_version_image_tags_when_bad_tag_then_refused(self):
        with pytest.raises(ValueError, match="not a release tag"):
            rt.version_image_tags("v1.6", self.EXISTING)


class TestReleaseNotes:
    def test_release_notes_when_entry_present_then_heading_through_next_entry(self):
        notes = rt.release_notes(CHANGELOG, "v1.6.6")
        assert notes.startswith("## [1.6.6] - 2026-11-21\n")
        assert "Reranked with Amazon Rerank (#624)" in notes
        assert "1.6.5" not in notes
        assert notes.endswith("(#624)\n")

    def test_release_notes_when_last_entry_then_reads_to_end(self):
        assert (
            rt.release_notes(CHANGELOG, "v1.6.5")
            == "## [1.6.5] - 2026-11-05\n\nPackaging release.\n"
        )

    def test_release_notes_when_entry_missing_then_refused(self):
        with pytest.raises(ValueError, match=r"no '## \[1.6.7\] - YYYY-MM-DD' entry"):
            rt.release_notes(CHANGELOG, "v1.6.7")

    def test_release_notes_when_entry_empty_then_refused(self):
        with pytest.raises(ValueError, match="entry for 1.7.0 is empty"):
            rt.release_notes(
                "## [1.7.0] - 2026-12-01\n\n## [1.6.6] - 2026-11-21\nx\n", "v1.7.0"
            )

    def test_release_notes_when_candidate_then_release_entry(self):
        assert rt.release_notes(CHANGELOG, "v1.6.6-rc.1") == rt.release_notes(
            CHANGELOG, "v1.6.6"
        )

    def test_release_notes_when_candidate_without_entry_then_refused(self):
        with pytest.raises(ValueError, match=r"no '## \[1.6.7\] - YYYY-MM-DD' entry"):
            rt.release_notes(CHANGELOG, "v1.6.7-rc.1")

    def test_release_notes_when_heading_has_no_date_then_refused(self):
        with pytest.raises(ValueError, match="no '## \\[1.7.0\\]"):
            rt.release_notes("## [1.7.0] - Unreleased\n\nSoon.\n", "v1.7.0")


class TestReleaseTitle:
    def test_release_title_when_annotated_tag_then_headline_in_title(self):
        title = rt.release_title("v1.6.6", "tag", "  Amazon Rerank and AWS  ")
        assert title == "Evidence Lab v1.6.6 — Amazon Rerank and AWS"

    def test_release_title_when_lightweight_tag_then_refused(self):
        with pytest.raises(ValueError, match="git tag -a v1.6.6"):
            rt.release_title("v1.6.6", "commit", "Merge pull request #1")

    def test_release_title_when_empty_message_then_refused(self):
        with pytest.raises(ValueError, match="message is empty"):
            rt.release_title("v1.6.6", "tag", "   ")

    def test_release_title_when_candidate_then_refused(self):
        with pytest.raises(ValueError, match="release candidate"):
            rt.release_title("v1.6.6-rc.1", "tag", "x")


def _run(
    name, event="push", conclusion="success", status="completed", number=1, sha=SHA
):
    """One workflow run, shaped as GitHub's ``actions/runs`` listing returns it."""
    return {
        "name": name,
        "event": event,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "run_number": number,
        "head_sha": sha,
        "head_branch": "main",
        "html_url": f"https://github.com/dividor/evidencelab/actions/runs/{number}",
    }


# What GitHub listed for main's b156148 on 2026-11-21: CI failed on the new image
# scan, while Demo E2E and Publish images (re-run after a Docker Hub 429) passed.
B156148_RUNS = [
    _run("pip in / for aiosmtplib - Update #1720611643", event="dynamic", number=238),
    _run("CI", conclusion="failure", number=2122),
    _run("Demo E2E", number=312),
    _run("Publish images", number=205),
]


class TestCheckTested:
    def test_check_tested_when_ci_and_demo_passed_then_accepted(self):
        runs = [_run("CI", number=2130), _run("Demo E2E", number=320)]
        assert rt.check_tested(runs, SHA) == "CI and Demo E2E passed for 3db0bba"

    def test_check_tested_when_ci_failed_then_refused_with_its_link(self):
        with pytest.raises(
            ValueError,
            match=(
                r"CI for 3db0bba ended 'failure' "
                r"\(https://github.com/dividor/evidencelab/actions/runs/2122\)"
            ),
        ):
            rt.check_tested(B156148_RUNS, SHA)

    def test_check_tested_when_publish_passed_then_it_does_not_stand_in_for_ci(self):
        runs = [_run("Publish images", number=205), _run("Demo E2E", number=312)]
        with pytest.raises(ValueError, match="CI has no run for 3db0bba"):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_only_the_pull_request_run_passed_then_refused(self):
        # A pull request's run tests a preview merge, not the commit itself.
        runs = [
            _run("CI", event="pull_request", number=2100),
            _run("Demo E2E", number=312),
        ]
        with pytest.raises(ValueError, match="CI has no run for 3db0bba"):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_still_running_then_refused(self):
        runs = [
            _run("CI", status="in_progress", number=2130),
            _run("Demo E2E", number=320),
        ]
        with pytest.raises(ValueError, match="CI for 3db0bba hasn't finished"):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_cancelled_then_refused(self):
        runs = [
            _run("CI", number=2130),
            _run("Demo E2E", conclusion="cancelled", number=320),
        ]
        with pytest.raises(ValueError, match="Demo E2E for 3db0bba ended 'cancelled'"):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_newer_run_failed_then_refused(self):
        runs = [
            _run("CI", number=2130),
            _run("CI", conclusion="failure", number=2131),
            _run("Demo E2E", number=320),
        ]
        with pytest.raises(ValueError, match="CI for 3db0bba ended 'failure'"):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_newer_run_passed_then_accepted(self):
        runs = [
            _run("CI", conclusion="failure", number=2130),
            _run("CI", number=2131),
            _run("Demo E2E", number=320),
        ]
        assert rt.check_tested(runs, SHA) == "CI and Demo E2E passed for 3db0bba"

    def test_check_tested_when_demo_started_by_hand_then_accepted(self):
        runs = [
            _run("CI", number=2130),
            _run("Demo E2E", event="workflow_dispatch", number=321),
        ]
        assert rt.check_tested(runs, SHA) == "CI and Demo E2E passed for 3db0bba"

    def test_check_tested_when_no_demo_run_then_says_how_to_start_one(self):
        with pytest.raises(
            ValueError, match="Demo E2E has no run for 3db0bba .*Run workflow"
        ):
            rt.check_tested([_run("CI", number=2130)], SHA)

    def test_check_tested_when_runs_are_for_another_commit_then_refused(self):
        runs = [
            _run("CI", number=2130, sha=OLDER_SHA),
            _run("Demo E2E", number=320, sha=OLDER_SHA),
        ]
        with pytest.raises(
            ValueError, match="CI has no run for 3db0bba; Demo E2E has no run"
        ):
            rt.check_tested(runs, SHA)

    def test_check_tested_when_short_hash_then_refused(self):
        with pytest.raises(ValueError, match="full 40-character commit hash"):
            rt.check_tested([], SHA[:7])


class TestMain:
    def test_main_when_branch_tags_then_one_name_per_line(self, capsys):
        assert (
            rt.main(["branch-tags", "--branch", "main", "--sha", SHA, "--head", SHA])
            == 0
        )
        assert capsys.readouterr().out == "main\nsha-3db0bba\n"

    def test_main_when_version_tags_then_reads_existing_file(self, tmp_path, capsys):
        existing = tmp_path / "tags.txt"
        existing.write_text("v1.6.5\nv1.6.6\n")
        assert (
            rt.main(["version-tags", "--tag", "v1.6.6", "--existing", str(existing)])
            == 0
        )
        assert capsys.readouterr().out.split() == ["1.6.6", "1.6", "latest"]

    def test_main_when_is_release_then_true_or_false(self, capsys):
        rt.main(["is-release", "--tag", "v1.6.6"])
        rt.main(["is-release", "--tag", "v1.6.6-rc.1"])
        assert capsys.readouterr().out.split() == ["true", "false"]

    def test_main_when_release_notes_then_prints_entry(self, tmp_path, capsys):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(CHANGELOG)
        assert (
            rt.main(["release-notes", "--tag", "v1.6.5", "--changelog", str(changelog)])
            == 0
        )
        assert (
            capsys.readouterr().out == "## [1.6.5] - 2026-11-05\n\nPackaging release.\n"
        )

    def test_main_when_release_title_then_prints_title(self, capsys):
        args = [
            "release-title",
            "--tag",
            "v1.6.6",
            "--tag-type",
            "tag",
            "--subject",
            "AWS",
        ]
        assert rt.main(args) == 0
        assert capsys.readouterr().out == "Evidence Lab v1.6.6 — AWS\n"

    def test_main_when_refused_then_exit_one_with_message(self, capsys):
        assert rt.main(["source-tag", "--sha", "nope"]) == 1
        assert "error: 'nope' is not a git commit hash" in capsys.readouterr().err

    def test_main_when_check_tested_passes_then_exit_zero(self, tmp_path, capsys):
        listing = tmp_path / "runs.json"
        listing.write_text(
            json.dumps(
                {"total_count": 2, "workflow_runs": [_run("CI"), _run("Demo E2E")]}
            )
        )
        assert rt.main(["check-tested", "--sha", SHA, "--runs", str(listing)]) == 0
        assert capsys.readouterr().out == "CI and Demo E2E passed for 3db0bba\n"

    def test_main_when_check_tested_fails_then_exit_one(self, tmp_path, capsys):
        listing = tmp_path / "runs.json"
        listing.write_text(
            json.dumps({"total_count": 4, "workflow_runs": B156148_RUNS})
        )
        assert rt.main(["check-tested", "--sha", SHA, "--runs", str(listing)]) == 1
        assert "error: CI for 3db0bba ended 'failure'" in capsys.readouterr().err

    def test_main_when_source_tag_then_prints_fixed_name(self, capsys):
        assert rt.main(["source-tag", "--sha", SHA]) == 0
        assert capsys.readouterr().out == "sha-3db0bba\n"
