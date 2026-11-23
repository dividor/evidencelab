"""Switching the AWS WAF allow list off on a running deployment works.

deploy/aws/cloudfront.tf makes the allow list's IP sets, and the web ACL rule
that references them, only while waf_allowed_ip_ranges has addresses. Turning
the list off removes both. AWS refuses to delete an IP set that a rule still
references (WAFAssociatedItemException), and Terraform's default order deletes
the IP sets before it updates the web ACL: measured with Terraform 1.17.2 on
stand-ins of the same shape, and seen on a real deployment, where the apply
stopped after five minutes of retries. With create_before_destroy on the IP
sets, Terraform updates the web ACL first, then deletes them.

The template's own Terraform tests mock the provider, so they can't show the
order; this test keeps the setting in place.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUDFRONT_TF = REPO_ROOT / "deploy" / "aws" / "cloudfront.tf"


def _resource_block(text: str, resource_type: str, name: str) -> str:
    """The body of one resource block, comments dropped, braces matched."""
    start = re.search(rf'^resource "{resource_type}" "{name}" \{{', text, re.MULTILINE)
    assert start, f"{resource_type}.{name} not found"
    depth, i = 0, start.end() - 1
    for i in range(start.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
    body = text[start.end() : i]
    return "\n".join(line.split("#", 1)[0] for line in body.splitlines())


def _lifecycle(block: str) -> str:
    match = re.search(r"lifecycle\s*\{([^{}]*)\}", block)
    return match.group(1) if match else ""


IP_SET = _resource_block(CLOUDFRONT_TF.read_text(), "aws_wafv2_ip_set", "allowed")


def test_ip_sets_when_allow_list_switched_off_then_web_acl_updates_before_they_go():
    assert re.search(r"create_before_destroy\s*=\s*true", _lifecycle(IP_SET))


def test_ip_sets_when_read_then_exist_only_with_an_allow_list():
    # The case the lifecycle setting is for: the sets come and go with the list.
    assert "local.waf_allow_list" in IP_SET


def test_resource_block_when_nested_and_commented_then_body_only():
    text = (
        'resource "a" "b" {\n  x = 1 # note {\n  lifecycle {\n    y = 2\n  }\n}\n'
        'resource "c" "d" {}\n'
    )
    block = _resource_block(text, "a", "b")
    assert "x = 1" in block and "note" not in block and "y = 2" in _lifecycle(block)
