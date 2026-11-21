#!/usr/bin/env bash
# Check that a deployment's site is up: deploy.sh's last step, also usable on
# its own.
#
# Usage: deploy/aws/scripts/check-site.sh
#
# Without a blocking WAF allow list, it fetches the site's / and /api/health,
# as a visitor would. With one (waf_allowed_ip_ranges set and waf_count_only
# false), the WAF answers 403 to every address not on the list, often
# including the machine running this, such as a CI agent. So instead it checks
# through AWS:
#   - CloudFront has finished deploying the distribution;
#   - the load balancer reports at least one healthy web app (ui) copy and
#     none unhealthy. Its health check fetches / from each copy.
# That doesn't fetch /api/health; deploy.sh has already waited for the api,
# mcp and embedding services to be running before this step.
#
# Retries every SITE_CHECK_INTERVAL seconds (default 10), SITE_CHECK_ATTEMPTS
# times (default 30). Needs terraform, curl, and the aws CLI for the allow-list
# case. Set TERRAFORM to run terraform some other way.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
attempts="${SITE_CHECK_ATTEMPTS:-30}"
interval="${SITE_CHECK_INTERVAL:-10}"
output() { $tf -chdir="$here" output -raw "$1"; }

site_url="$(output site_url)"
allow_list_blocks="$(output waf_allow_list_blocks)"

check_over_the_internet() {
    curl -fsS -o /dev/null "$site_url/" && curl -fsS -o /dev/null "$site_url/api/health"
}

check_through_aws() {
    local status states state healthy=0
    status="$(aws cloudfront get-distribution --id "$distribution" --query Distribution.Status --output text)"
    states="$(aws elbv2 describe-target-health --region "$region" --target-group-arn "$target_group" \
        --query 'TargetHealthDescriptions[].TargetHealth.State' --output text)"
    echo "  CloudFront: $status; web app copies: ${states:-none}"
    [ "$status" = Deployed ] || return 1
    # At least one healthy copy, and none unhealthy or still starting.
    # (Draining copies are old ones on their way out.)
    for state in $states; do
        case "$state" in
            healthy) healthy=$((healthy + 1)) ;;
            draining) ;;
            *) return 1 ;;
        esac
    done
    [ "$healthy" -gt 0 ]
}

if [ "$allow_list_blocks" = true ]; then
    distribution="$(output cloudfront_distribution_id)"
    target_group="$(output ui_target_group_arn)"
    region="$(output region)"
    echo "The site lets in only the addresses in waf_allowed_ip_ranges, so it is checked through AWS:"
    check=check_through_aws
else
    check=check_over_the_internet
fi

for attempt in $(seq 1 "$attempts"); do
    if $check; then
        echo "The site is up: $site_url"
        exit 0
    fi
    if [ "$attempt" = "$attempts" ]; then
        echo "The site did not come up at $site_url" >&2
        exit 1
    fi
    sleep "$interval"
done
