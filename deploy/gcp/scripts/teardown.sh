#!/usr/bin/env bash
# Remove a Google Cloud deployment made with deploy.sh, and confirm Terraform
# no longer manages anything for it.
#
# Usage: deploy/gcp/scripts/teardown.sh [--yes]
#
#   --yes  Destroy without asking first.
#
# This deletes the database, the document bucket and Qdrant with all their
# data. The APIs the deployment enabled stay enabled. Cloud Run keeps the
# addresses it reserved in the subnet for 1-2 hours after its services and
# jobs are deleted, and the subnet cannot be deleted until then, so the script
# may wait that long before it finishes. Needs terraform and gcloud. Set
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
# Read the settings from the variables, not the outputs: a destroy that stopped
# partway leaves the state with no outputs.
setting() { echo "var.$1" | $tf -chdir="$here" console | tr -d '"'; }

name="$(setting name)"
project="$(setting project_id)"
region="$(setting region)"

# Destroy with the configuration the deployment was made with.
destroy_vars=()
if [ -f "$here/.demo/config.json" ]; then
    destroy_vars=(-var "config_json_path=.demo/config.json")
fi

destroy() {
    $tf -chdir="$here" destroy -input=false "$@" ${destroy_vars[@]+"${destroy_vars[@]}"}
}

# Addresses Cloud Run reserved in the deployment's subnet for its instances.
cloud_run_addresses() {
    gcloud compute addresses list --project "$project" \
        --filter="purpose=SERVERLESS AND subnetwork~/regions/$region/subnetworks/$name\$" \
        --format='value(name)'
}

if ! destroy ${auto_approve[@]+"${auto_approve[@]}"}; then
    # Google documents a 1-2 hour wait for Cloud Run to release its addresses
    # after its services and jobs are deleted. Any other failure stops here.
    if [ -z "$(cloud_run_addresses)" ]; then
        exit 1
    fi
    echo
    echo "==> Waiting for Cloud Run to release its addresses in the subnet $name"
    echo "    Google says this takes 1-2 hours. Checking every 5 minutes, for up to 3 hours."
    deadline=$((SECONDS + 3 * 3600))
    while [ -n "$(cloud_run_addresses)" ]; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "Cloud Run still holds these addresses after 3 hours; run teardown.sh again later:" >&2
            cloud_run_addresses >&2
            exit 1
        fi
        sleep 300
    done
    echo "==> Released; deleting the rest"
    # Only what the first destroy listed and could not delete is left.
    destroy -auto-approve
fi

# Terraform's state lists everything it still manages: it must be empty.
remaining="$($tf -chdir="$here" state list)"
if [ -n "$remaining" ]; then
    echo "Terraform still manages these resources; run teardown.sh again:" >&2
    while IFS= read -r resource; do echo "  $resource" >&2; done <<<"$remaining"
    exit 1
fi
echo
echo "Everything Terraform created for $name in $project is deleted."
