"""Unit tests for scripts/sync/repo/sync_repo_to_azure_devops.py.

The script mirrors branches/tags from a source remote to an Azure DevOps
repository. Tests stub ``subprocess.run`` so they execute without git or
network access, and verify that credentials are only ever referenced via
environment-variable expansion — never embedded in commands.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sync"
    / "repo"
    / "sync_repo_to_azure_devops.py"
)
_spec = importlib.util.spec_from_file_location(
    "sync_repo_to_azure_devops", _SCRIPT_PATH
)
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)

_URL = "https://dev.azure.com/example-org/example-project/_git/example-repo"
_SENTINEL_VALUE = "sentinel-token-value"


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail():
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")


def _set_required_env(monkeypatch):
    monkeypatch.setenv(sync_mod.ENV_REPO_URL, _URL)
    monkeypatch.setenv(sync_mod.ENV_CREDENTIAL, _SENTINEL_VALUE)


@pytest.mark.unit
class TestRequireEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("SYNC_TEST_VAR", "value")
        assert sync_mod._require_env("SYNC_TEST_VAR") == "value"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("SYNC_TEST_VAR", raising=False)
        with pytest.raises(RuntimeError, match="SYNC_TEST_VAR"):
            sync_mod._require_env("SYNC_TEST_VAR")

    def test_raises_when_blank(self, monkeypatch):
        monkeypatch.setenv("SYNC_TEST_VAR", "   ")
        with pytest.raises(RuntimeError, match="SYNC_TEST_VAR"):
            sync_mod._require_env("SYNC_TEST_VAR")


@pytest.mark.unit
class TestMaskUrl:
    def test_strips_userinfo(self):
        url = "https://someone@dev.azure.com/org/project/_git/repo"
        assert sync_mod._mask_url(url) == "https://dev.azure.com/org/project/_git/repo"

    def test_leaves_plain_url_unchanged(self):
        assert sync_mod._mask_url(_URL) == _URL


@pytest.mark.unit
class TestBuildRefspecs:
    def test_maps_remote_branches_to_target_heads(self):
        refspecs = sync_mod._build_refspecs("origin", ["main", "rc/v1.0.0"], tags=False)
        assert refspecs == [
            "refs/remotes/origin/main:refs/heads/main",
            "refs/remotes/origin/rc/v1.0.0:refs/heads/rc/v1.0.0",
        ]

    def test_appends_tag_refspec_when_tags_enabled(self):
        refspecs = sync_mod._build_refspecs("origin", ["main"], tags=True)
        assert refspecs[-1] == "refs/tags/*:refs/tags/*"


@pytest.mark.unit
class TestBuildPushArgs:
    def test_dry_run_adds_flag(self):
        args = sync_mod._build_push_args(_URL, ["a:b"], dry_run=True, force=False)
        assert "--dry-run" in args

    def test_no_dry_run_omits_flag(self):
        args = sync_mod._build_push_args(_URL, ["a:b"], dry_run=False, force=False)
        assert "--dry-run" not in args

    def test_force_adds_flag(self):
        args = sync_mod._build_push_args(_URL, ["a:b"], dry_run=False, force=True)
        assert "--force" in args

    def test_url_precedes_refspecs(self):
        args = sync_mod._build_push_args(
            _URL, ["a:b", "c:d"], dry_run=False, force=False
        )
        assert args[-3:] == [_URL, "a:b", "c:d"]

    def test_credentials_come_from_env_expansion_not_values(self, monkeypatch):
        """The password must never be embedded in the command; the helper
        expands the environment variable when git itself runs it."""
        monkeypatch.setenv(sync_mod.ENV_CREDENTIAL, _SENTINEL_VALUE)
        args = sync_mod._build_push_args(_URL, ["a:b"], dry_run=True, force=False)
        assert all(_SENTINEL_VALUE not in part for part in args)
        helper = next(part for part in args if part.startswith("credential.helper=!"))
        assert "${AZURE_DEVOPS_PASSWORD}" in helper


def _branch_listing(names):
    """CompletedProcess mimicking ``git for-each-ref`` stdout."""
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout="\n".join(names) + "\n", stderr=""
    )


@pytest.mark.unit
class TestDefaultBranches:
    _REMOTE_NAMES = [
        "HEAD",
        "dependabot/pip/thing",
        "feature/x",
        "main",
        "rc/v1.6.0",
        "rc/v1.6.1",
        "v2-experiments",
    ]

    def test_selects_main_and_rc_and_v_branches(self, tmp_path):
        with patch.object(
            sync_mod.subprocess, "run", return_value=_branch_listing(self._REMOTE_NAMES)
        ):
            branches = sync_mod._default_branches("origin", tmp_path)
        assert branches == ["main", "rc/v1.6.0", "rc/v1.6.1", "v2-experiments"]

    def test_main_sorts_first(self, tmp_path):
        with patch.object(
            sync_mod.subprocess,
            "run",
            return_value=_branch_listing(["rc/v1.0.0", "main"]),
        ):
            branches = sync_mod._default_branches("origin", tmp_path)
        assert branches[0] == "main"

    def test_raises_when_nothing_matches(self, tmp_path):
        with patch.object(
            sync_mod.subprocess,
            "run",
            return_value=_branch_listing(["feature/x", "dev"]),
        ):
            with pytest.raises(RuntimeError, match="default pattern"):
                sync_mod._default_branches("origin", tmp_path)

    def test_raises_when_listing_fails(self, tmp_path):
        with patch.object(sync_mod.subprocess, "run", return_value=_fail()):
            with pytest.raises(RuntimeError, match="Could not list branches"):
                sync_mod._default_branches("origin", tmp_path)


@pytest.mark.unit
class TestVerifyBranches:
    def test_raises_when_branch_missing(self, tmp_path):
        with patch.object(sync_mod.subprocess, "run", return_value=_fail()):
            with pytest.raises(RuntimeError, match="missing-branch"):
                sync_mod._verify_branches("origin", ["missing-branch"], tmp_path)

    def test_passes_when_branch_exists(self, tmp_path):
        with patch.object(sync_mod.subprocess, "run", return_value=_ok()) as run:
            sync_mod._verify_branches("origin", ["main"], tmp_path)
        ref_args = run.call_args_list[0].args[0]
        assert "refs/remotes/origin/main" in ref_args


@pytest.mark.unit
class TestSyncToAzureDevops:
    def _sync(self, tmp_path, **overrides):
        kwargs = {
            "root_dir": tmp_path,
            "remote": "origin",
            "branches": ["main"],
            "tags": False,
            "dry_run": True,
            "force": False,
        }
        kwargs.update(overrides)
        sync_mod.sync_to_azure_devops(**kwargs)

    def test_raises_when_repo_url_env_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv(sync_mod.ENV_REPO_URL, raising=False)
        monkeypatch.setenv(sync_mod.ENV_CREDENTIAL, _SENTINEL_VALUE)
        with pytest.raises(RuntimeError, match=sync_mod.ENV_REPO_URL):
            self._sync(tmp_path)

    def test_raises_when_pat_env_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv(sync_mod.ENV_REPO_URL, _URL)
        monkeypatch.delenv(sync_mod.ENV_CREDENTIAL, raising=False)
        with pytest.raises(RuntimeError, match=sync_mod.ENV_CREDENTIAL):
            self._sync(tmp_path)

    def test_dry_run_passes_flag_to_git_push(self, tmp_path, monkeypatch):
        _set_required_env(monkeypatch)
        with patch.object(sync_mod.subprocess, "run", return_value=_ok()) as run:
            self._sync(tmp_path, dry_run=True)
        push_cmd = run.call_args_list[-1].args[0]
        assert "--dry-run" in push_cmd
        assert push_cmd[-2:] == [_URL, "refs/remotes/origin/main:refs/heads/main"]

    def test_real_run_omits_dry_run_flag(self, tmp_path, monkeypatch):
        _set_required_env(monkeypatch)
        with patch.object(sync_mod.subprocess, "run", return_value=_ok()) as run:
            self._sync(tmp_path, dry_run=False)
        push_cmd = run.call_args_list[-1].args[0]
        assert "--dry-run" not in push_cmd

    def test_raises_when_fetch_fails(self, tmp_path, monkeypatch):
        _set_required_env(monkeypatch)
        with patch.object(sync_mod.subprocess, "run", return_value=_fail()):
            with pytest.raises(RuntimeError, match="Fetch from remote"):
                self._sync(tmp_path)

    def test_raises_when_push_fails(self, tmp_path, monkeypatch):
        _set_required_env(monkeypatch)
        with patch.object(sync_mod.subprocess, "run") as run:
            run.side_effect = [_ok(), _ok(), _fail()]  # fetch, rev-parse, push
            with pytest.raises(RuntimeError, match="Push to Azure DevOps failed"):
                self._sync(tmp_path)

    def test_no_branches_discovers_main_and_release_branches(
        self, tmp_path, monkeypatch
    ):
        _set_required_env(monkeypatch)
        listing = _branch_listing(["HEAD", "feature/x", "main", "rc/v1.6.1"])
        with patch.object(sync_mod.subprocess, "run") as run:
            # fetch, for-each-ref, rev-parse x2, push
            run.side_effect = [_ok(), listing, _ok(), _ok(), _ok()]
            self._sync(tmp_path, branches=None)
        push_cmd = run.call_args_list[-1].args[0]
        assert push_cmd[-2:] == [
            "refs/remotes/origin/main:refs/heads/main",
            "refs/remotes/origin/rc/v1.6.1:refs/heads/rc/v1.6.1",
        ]
        assert not any("feature/x" in part for part in push_cmd)


@pytest.mark.unit
class TestMain:
    def test_returns_error_code_when_env_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv(sync_mod.ENV_REPO_URL, raising=False)
        monkeypatch.delenv(sync_mod.ENV_CREDENTIAL, raising=False)
        monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])
        with patch.object(sync_mod, "_load_env", return_value=tmp_path):
            assert sync_mod.main() == 1

    def test_returns_zero_on_success(self, tmp_path, monkeypatch):
        _set_required_env(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])
        with patch.object(sync_mod, "_load_env", return_value=tmp_path):
            with patch.object(sync_mod.subprocess, "run") as run:
                # fetch, for-each-ref, rev-parse, push
                run.side_effect = [_ok(), _branch_listing(["main"]), _ok(), _ok()]
                assert sync_mod.main() == 0
