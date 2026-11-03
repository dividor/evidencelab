#!/usr/bin/env bash
# Remove an AWS deployment made with deploy.sh, then list anything still
# tagged with its name.
#
# Usage: deploy/aws/scripts/teardown.sh [--yes]
#
#   --yes  Destroy without asking first.
#
# This deletes the database, the file share and Qdrant with all their data.
# Unless db_skip_final_snapshot is true, RDS keeps a final snapshot named
# <name>-final, which you delete yourself when it is no longer needed.
# Needs terraform and the aws CLI. Set AWS_PROFILE to pick the AWS account,
# and TERRAFORM to run terraform some other way.
set -euo pipefail

auto_approve=()
case "${1:-}" in
    "") ;;
    --yes) auto_approve=(-auto-approve) ;;
    *) echo "usage: teardown.sh [--yes]" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
output() { $tf -chdir="$here" output -raw "$1"; }

name="$(output name)"
region="$(output region)"

# Destroy with the configuration the deployment was made with.
destroy_vars=()
if [ -f "$here/.demo/config.json" ]; then
    destroy_vars=(-var "config_json_path=.demo/config.json")
fi

$tf -chdir="$here" destroy -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${destroy_vars[@]+"${destroy_vars[@]}"}

echo
echo "Resources still tagged Deployment=$name (AWS can take a few minutes to drop deleted ones):"
left="$(aws resourcegroupstaggingapi get-resources --region "$region" \
    --tag-filters "Key=Deployment,Values=$name" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text)"
if [ -z "$left" ] || [ "$left" = None ]; then
    echo "  none"
else
    echo "$left" | tr '\t' '\n' | sed 's/^/  /'
fi
