#!/usr/bin/env bash
# Remove an Azure deployment made with deploy.sh, and confirm its resource
# group is gone.
#
# Usage: deploy/azure/scripts/teardown.sh [--yes]
#
#   --yes  Destroy without asking first.
#
# This deletes the database, the file share and Qdrant with all their data.
# Needs terraform and the az CLI. Set TERRAFORM to run terraform some other way.
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

subscription="$(output subscription_id)"
group="$(output resource_group)"

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

# Everything the deployment made was in its resource group, which Terraform
# deletes last, so it must be gone too.
if [ "$(az group exists --subscription "$subscription" --name "$group")" != false ]; then
    echo "The resource group $group still exists. See what is in it with:" >&2
    echo "  az resource list --subscription $subscription --resource-group $group -o table" >&2
    exit 1
fi
echo
echo "Everything Terraform created for $group is deleted, and the resource group is gone."
