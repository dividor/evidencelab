"""deploy/aws/scripts/check-site.sh: deploy.sh's last step.

Without a blocking WAF allow list it fetches the site like a visitor. With one,
the machine running it (often a CI agent) may get 403 from the WAF, so it
checks through AWS instead: CloudFront deployed, and the load balancer's web
app copies healthy. These tests run the script with stand-ins for terraform,
aws and curl on PATH, and read back which of them it called.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "aws" / "scripts" / "check-site.sh"
SITE = "https://d111111abcdef8.cloudfront.net"
TARGET_GROUP = (
    "arn:aws:elasticloadbalancing:eu-west-1:123456789012:targetgroup/x-ui/abc"
)

# Each stand-in logs its arguments, and answers from the scenario in SCENARIO.
STAND_IN = r"""#!/usr/bin/env python3
import json, os, sys
name = os.path.basename(sys.argv[0])
scenario = json.load(open(os.environ["SCENARIO"]))
calls = os.environ["CALLS"]
with open(calls, "a") as log:
    log.write(json.dumps([name] + sys.argv[1:]) + "\n")
n = sum(1 for line in open(calls) if json.loads(line)[0] == name)
args = sys.argv[1:]
if name == "terraform":
    print(scenario["outputs"][args[-1]], end="")
elif name == "curl":
    sys.exit(scenario["curl_exit"])
elif name == "aws" and args[0] == "cloudfront":
    answers = scenario["cloudfront"]
    print(answers[min(n, len(answers)) - 1])
elif name == "aws" and args[0] == "elbv2":
    answers = scenario["targets"]
    print(answers[min(n, len(answers)) - 1])
"""


def run_check(
    tmp_path,
    allow_list_blocks,
    curl_exit=0,
    cloudfront=("Deployed",),
    targets=("healthy",),
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("terraform", "aws", "curl"):
        tool = bin_dir / name
        tool.write_text(STAND_IN)
        tool.chmod(0o755)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "outputs": {
                    "site_url": SITE,
                    "waf_allow_list_blocks": "true" if allow_list_blocks else "false",
                    "cloudfront_distribution_id": "E2EXAMPLE",
                    "ui_target_group_arn": TARGET_GROUP,
                    "region": "eu-west-1",
                },
                "curl_exit": curl_exit,
                "cloudfront": list(cloudfront),
                "targets": list(targets),
            }
        )
    )
    calls = tmp_path / "calls.log"
    calls.write_text("")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SCENARIO": str(scenario),
        "CALLS": str(calls),
        "SITE_CHECK_ATTEMPTS": "3",
        "SITE_CHECK_INTERVAL": "0",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False
    )
    logged = [json.loads(line) for line in calls.read_text().splitlines()]
    return result, logged


def called(logged, name):
    return [c[1:] for c in logged if c[0] == name]


def test_check_when_no_allow_list_then_fetches_the_site_and_health(tmp_path):
    result, logged = run_check(tmp_path, allow_list_blocks=False)
    assert result.returncode == 0, result.stderr
    assert [c[-1] for c in called(logged, "curl")] == [f"{SITE}/", f"{SITE}/api/health"]
    assert called(logged, "aws") == []


def test_check_when_no_allow_list_and_site_down_then_fails_after_retries(tmp_path):
    result, logged = run_check(tmp_path, allow_list_blocks=False, curl_exit=22)
    assert result.returncode == 1
    assert "did not come up" in result.stderr
    assert (
        len(called(logged, "curl")) == 3
    )  # three attempts, each stopping at the first fetch


def test_check_when_allow_list_blocks_then_checks_through_aws_not_the_internet(
    tmp_path,
):
    result, logged = run_check(tmp_path, allow_list_blocks=True)
    assert result.returncode == 0, result.stderr
    assert called(logged, "curl") == []
    assert "checked through AWS" in result.stdout
    cloudfront, targets = called(logged, "aws")
    assert (
        cloudfront[:3] == ["cloudfront", "get-distribution", "--id"]
        and "E2EXAMPLE" in cloudfront
    )
    assert targets[:2] == ["elbv2", "describe-target-health"] and "eu-west-1" in targets
    assert TARGET_GROUP in targets


def test_check_when_cloudfront_still_deploying_then_waits_for_it(tmp_path):
    result, logged = run_check(
        tmp_path, allow_list_blocks=True, cloudfront=("InProgress", "Deployed")
    )
    assert result.returncode == 0, result.stderr
    assert len(called(logged, "aws")) == 4  # two attempts, two calls each


@pytest.mark.parametrize(
    "states", ["healthy\tdraining", "draining\thealthy", "healthy\thealthy"]
)
def test_check_when_healthy_copies_with_old_ones_draining_then_up(tmp_path, states):
    result, _ = run_check(tmp_path, allow_list_blocks=True, targets=(states,))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "states", ["", "draining", "initial", "healthy\tunhealthy", "unavailable"]
)
def test_check_when_no_healthy_copy_or_one_unhealthy_then_fails(tmp_path, states):
    result, _ = run_check(tmp_path, allow_list_blocks=True, targets=(states,))
    assert result.returncode == 1
    assert "did not come up" in result.stderr
