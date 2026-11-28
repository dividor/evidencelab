"""CI's weekly run scans main for security issues and runs nothing else.

A pull request is the only other time the scanners run, so a new advisory
against code that hasn't changed would go unnoticed until the next merge. The
schedule (and a run started by hand) runs code-quality, security-scan, sbom and
container-scan with the same rules that block a pull request; the unit, UI,
integration and Terraform tests run only on pushes and pull requests.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
WORKFLOW = yaml.safe_load(CI.read_text())
# PyYAML reads the bare key `on` as True.
TRIGGERS = WORKFLOW.get("on", WORKFLOW.get(True))
JOBS = WORKFLOW["jobs"]

SECURITY_JOBS = ["code-quality", "security-scan", "sbom", "container-scan"]
PUSH_OR_PULL_REQUEST = (
    "github.event_name == 'push' || github.event_name == 'pull_request'"
)


def test_triggers_when_read_then_weekly_schedule_and_by_hand():
    assert TRIGGERS["schedule"] == [{"cron": "0 5 * * 1"}]
    assert "workflow_dispatch" in TRIGGERS


def test_triggers_when_read_then_pushes_and_pull_requests_unchanged():
    assert TRIGGERS["push"] == {"branches": ["main", "release-*", "copilot/**"]}
    assert TRIGGERS["pull_request"] == {"branches": ["main", "release-*"]}


@pytest.mark.parametrize("job", SECURITY_JOBS)
def test_security_job_when_scheduled_then_not_held_back_by_event(job):
    assert "event_name" not in JOBS[job].get("if", "")


@pytest.mark.parametrize("job", ["tests", "ui-tests", "terraform"])
def test_test_job_when_read_then_runs_only_on_push_or_pull_request(job):
    assert JOBS[job]["if"] == PUSH_OR_PULL_REQUEST


def test_integration_tests_when_read_then_need_a_push_or_this_repos_pull_request():
    condition = JOBS["integration-tests"]["if"]
    assert "(github.event_name == 'push' || github.event.pull_request" in condition


def test_security_jobs_when_read_then_need_only_each_other():
    assert "needs" not in JOBS["code-quality"]
    assert JOBS["security-scan"]["needs"] == "code-quality"
    assert JOBS["sbom"]["needs"] == "security-scan"
    assert JOBS["container-scan"]["needs"] == "security-scan"
