#!/usr/bin/env bash
# Remove a Google Cloud deployment made with deploy.sh, and confirm Terraform
# no longer manages anything for it.
#
# Usage: deploy/gcp/scripts/teardown.sh [--yes]
#
#   --yes  Destroy without asking first.
#
# This deletes the database, the document bucket and Qdrant with all their
# data. The APIs the deployment enabled stay enabled. Needs terraform. Set
# TERRAFORM to run terraform some other way.
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
project="$(output project_id)"

# Destroy with the configuration the deployment was made with.
destroy_vars=()
if [ -f "$here/.demo/config.json" ]; then
    destroy_vars=(-var "config_json_path=.demo/config.json")
fi

$tf -chdir="$here" destroy -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${destroy_vars[@]+"${destroy_vars[@]}"}

# Terraform's state lists everything it still manages: it must be empty.
remaining="$($tf -chdir="$here" state list)"
if [ -n "$remaining" ]; then
    echo "Terraform still manages these resources; run teardown.sh again:" >&2
    while IFS= read -r resource; do echo "  $resource" >&2; done <<<"$remaining"
    exit 1
fi
echo
echo "Everything Terraform created for $name in $project is deleted."
