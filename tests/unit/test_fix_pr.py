"""Tests for scripts/ci/fix_pr.py: the fix pull request after a review check."""

import json
import subprocess

import pytest

import scripts.ci.fix_pr as fp

pytestmark = pytest.mark.unit

SHA = "3db0bba" + "0" * 33
DOCS_VERDICT = {
    "needs_docs": True,
    "covered": False,
    "reason": "Adds a setting.",
    "missing": [
        {"what": "What the limit does", "where": "docs/admin/system-monitoring.md"}
    ],
    "notes": [],
}
UX_VERDICT = {
    "verdict": "looks good",
    "summary": "Fine, two things to fix.",
    "screens": [],
    "findings": [
        {
            "severity": "should fix",
            "where": "Documents, 1440x900",
            "what": "Faint focus",
            "fix": "x",
        }
    ],
}


def _env(verdict):
    return {
        "PR": "693",
        "HEAD_REF": "ci/pr-docs-ux-checks",
        "SHA": SHA,
        "REPO": "o/r",
        "RUN_URL": "https://example.org/run/1",
        "VERDICT": json.dumps(verdict),
    }


class FakeCommands:
    """Stands in for subprocess.run of git and the GitHub CLI; records each call."""

    def __init__(self, status="", open_prs=None, create_error=None):
        self.status = status
        self.open_prs = open_prs or []
        self.create_error = create_error
        self.calls = []

    def __call__(self, args, input=None, capture_output=True, text=True, check=False):
        self.calls.append((args, input))
        out, code, err = "", 0, ""
        if args[:2] == ["git", "status"]:
            out = self.status
        elif args[1:3] == ["pr", "list"]:
            out = json.dumps(self.open_prs)
        elif args[1:3] == ["pr", "create"]:
            if self.create_error:
                code, err = 1, self.create_error
            else:
                out = "https://github.com/o/r/pull/700\n"
        return subprocess.CompletedProcess(args, code, out, err)

    def commands(self):
        return [args for args, _ in self.calls]


class TestChangedPaths:
    def test_changed_paths_when_edits_and_renames_then_lists_both_sides(self):
        cmds = FakeCommands(
            status=" M docs/a.md\n?? docs/new.md\nR  docs/old.md -> docs/b.md\n"
        )

        assert fp.changed_paths(cmds) == [
            "docs/a.md",
            "docs/new.md",
            "docs/old.md",
            "docs/b.md",
        ]

    def test_outside_when_paths_mixed_then_returns_only_the_stray_ones(self):
        paths = ["docs/a.md", "ui/frontend/src/App.css", "README.md"]

        assert fp.outside(paths, ("docs/",)) == ["ui/frontend/src/App.css", "README.md"]


class TestOpenFixPr:
    def test_open_when_nothing_changed_then_opens_nothing(self):
        cmds = FakeCommands(status="")

        assert fp.open_fix_pr("docs", _env(DOCS_VERDICT), run=cmds) == 0
        assert all(args[:2] != ["git", "push"] for args in cmds.commands())

    def test_open_when_edits_outside_the_area_then_refuses(self, capsys):
        cmds = FakeCommands(status=" M docs/a.md\n M scripts/ci/fix_pr.py\n")

        assert fp.open_fix_pr("docs", _env(DOCS_VERDICT), run=cmds) == 1
        assert "scripts/ci/fix_pr.py" in capsys.readouterr().err
        assert all(args[:2] != ["git", "push"] for args in cmds.commands())

    def test_open_when_docs_written_then_commits_pushes_and_opens_into_the_pr_branch(
        self,
    ):
        cmds = FakeCommands(status=" M docs/admin/system-monitoring.md\n")

        assert fp.open_fix_pr("docs", _env(DOCS_VERDICT), run=cmds) == 0

        commands = cmds.commands()
        branch = "docs-fix/pr-693-3db0bba"
        assert ["git", "checkout", "-b", branch] in commands
        assert ["git", "add", "-A", "--", "docs/"] in commands
        assert ["git", "push", "origin", branch] in commands
        create, body = next((a, i) for a, i in cmds.calls if a[1:3] == ["pr", "create"])
        assert create[create.index("--base") + 1] == "ci/pr-docs-ux-checks"
        assert create[create.index("--head") + 1] == branch
        assert "#693" in create[create.index("--title") + 1]
        assert "- **docs/admin/system-monitoring.md**: What the limit does" in body

    def test_open_when_commit_made_then_it_is_the_bots_and_names_no_one_else(self):
        cmds = FakeCommands(status=" M ui/frontend/src/App.css\n")

        fp.open_fix_pr("ux", _env(UX_VERDICT), run=cmds)

        commit = next(args for args in cmds.commands() if "commit" in args)
        assert f"user.name={fp.BOT_NAME}" in commit
        assert commit[-1] == "fix(ui): address the UX review of #693"

    def test_open_when_an_older_fix_is_open_then_closes_it_first(self):
        older = [
            {"number": 698, "headRefName": "ux-fix/pr-693-aaaaaaa"},
            {"number": 699, "headRefName": "ux-fix/pr-701-bbbbbbb"},
            {"number": 697, "headRefName": "docs-fix/pr-693-ccccccc"},
        ]
        cmds = FakeCommands(status=" M ui/frontend/src/App.css\n", open_prs=older)

        fp.open_fix_pr("ux", _env(UX_VERDICT), run=cmds)

        closed = [args[3] for args in cmds.commands() if args[1:3] == ["pr", "close"]]
        assert closed == ["698"]

    def test_open_when_github_refuses_then_says_which_setting_allows_it(self, capsys):
        cmds = FakeCommands(
            status=" M docs/a.md\n",
            create_error="GitHub Actions is not permitted to create or approve pull requests",
        )

        assert fp.open_fix_pr("docs", _env(DOCS_VERDICT), run=cmds) == 1
        assert (
            "Allow GitHub Actions to create and approve pull requests"
            in capsys.readouterr().err
        )
        assert ["git", "push", "origin", "--delete", "docs-fix/pr-693-3db0bba"] in (
            cmds.commands()
        )

    def test_open_when_create_fails_otherwise_then_raises(self):
        cmds = FakeCommands(status=" M docs/a.md\n", create_error="HTTP 502")

        with pytest.raises(RuntimeError, match="HTTP 502"):
            fp.open_fix_pr("docs", _env(DOCS_VERDICT), run=cmds)
        assert ["git", "push", "origin", "--delete", "docs-fix/pr-693-3db0bba"] in (
            cmds.commands()
        )


class TestFixBody:
    def test_body_when_ux_then_lists_each_finding_with_its_severity(self):
        body = fp.fix_body("ux", UX_VERDICT, "693", "https://example.org/run/1")

        assert "The UX review found these problems in #693" in body
        assert "- **should fix**, Documents, 1440x900: Faint focus" in body
        assert "`ui/frontend/src/`" in body


class TestMain:
    @pytest.mark.parametrize("argv", [[], ["lint"], ["docs", "ux"]])
    def test_main_when_unknown_kind_then_usage(self, argv, capsys):
        assert fp.main(argv) == 2
        assert "usage" in capsys.readouterr().err
