#!/usr/bin/env bash
# Deploy Evidence Lab to Azure Container Apps, end to end.
#
# Usage: deploy/azure/scripts/deploy.sh [--demo DOCS] [--yes]
#
#   --demo DOCS  Also download and process DOCS World Bank demo documents,
#                with the demo data source from scripts/demo/run_demo.py and
#                the deployment's own Azure AI Foundry models. The site is
#                then usable without signing in: the web app is built with
#                the API key (anonymous_access).
#   --yes        Apply Terraform changes without asking first.
#
# Steps:
#   1. terraform apply: resource group, network, database, Redis, file share,
#      Qdrant, image registry, Foundry models, Container Apps environment
#      and jobs
#   2. build the web app image and push it to the registry
#   3. run the migrate job
#   4. create or update the ui, api, mcp and embedding apps
#   5. wait until the apps are running
#   6. with --demo, download and process the demo documents
#   7. check the site answers, and print its address
#
# Run it again to upgrade: it applies changes, builds a new web app image,
# migrates, then moves the apps to new revisions. Reads terraform.tfvars in
# deploy/azure. Needs terraform, docker (with buildx), the az CLI, python3 and
# curl. Set TERRAFORM to run terraform some other way.
set -euo pipefail

demo_docs=""
auto_approve=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --demo) demo_docs="${2:?--demo needs a number of documents}"; shift 2 ;;
        --yes) auto_approve=(-auto-approve); shift ;;
        *) echo "usage: deploy.sh [--demo DOCS] [--yes]" >&2; exit 2 ;;
    esac
done

here="$(cd "$(dirname "$0")/.." && pwd)"
scripts="$here/scripts"
tf="${TERRAFORM:-terraform}"
output() { $tf -chdir="$here" output -raw "$1"; }
step() { printf '\n==> %s\n' "$*"; }

if [ ! -f "$here/terraform.tfvars" ]; then
    echo "No deploy/azure/terraform.tfvars. Copy terraform.tfvars.example and fill it in." >&2
    exit 1
fi

# With --demo, the deployment runs a config.json with the demo data source and
# the Azure AI Foundry models, written by deploy/demo_config.py.
deploy_vars=()
if [ -n "$demo_docs" ]; then
    step "Writing the demo configuration"
    python3 "$here/../demo_config.py" --provider azure_foundry --out-dir "$here/.demo"
    demo_source="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["data_source"])' "$here/.demo/demo.json")"
    deploy_vars=(-var "config_json_path=.demo/config.json" -var "anonymous_access=true")
fi

$tf -chdir="$here" init -input=false >/dev/null

# Keep the apps as they are on this first apply: running the current web app
# image for an upgrade, not created yet for a new or torn-down deployment,
# whose state has no outputs.
services_now=false
ui_tag_now=latest
if [ "$(output services_enabled 2>/dev/null)" = true ]; then
    services_now=true
    ui_tag_now="$(output ui_image_tag)"
fi

step "1/7 Creating or updating the infrastructure"
$tf -chdir="$here" apply -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${deploy_vars[@]+"${deploy_vars[@]}"} \
    -var "services_enabled=$services_now" -var "ui_image_tag=$ui_tag_now"

subscription="$(output subscription_id)"
group="$(output resource_group)"

step "2/7 Building and pushing the web app image"
ui_tag="$(date -u +%Y%m%d%H%M%S)"
"$scripts/build-ui-image.sh" "$ui_tag"

step "3/7 Running the database migrations"
"$scripts/run-job.sh" migrate

step "4/7 Creating or updating the apps"
$tf -chdir="$here" apply -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${deploy_vars[@]+"${deploy_vars[@]}"} \
    -var "services_enabled=true" -var "ui_image_tag=$ui_tag"

step "5/7 Waiting for the apps"
apps="$($tf -chdir="$here" output -json apps | python3 -c 'import json, sys; print(" ".join(json.load(sys.stdin)))')"
for attempt in $(seq 1 90); do
    pending=""
    for app in $apps; do
        ready="$(az containerapp show --subscription "$subscription" --resource-group "$group" --name "$app" \
            --query "properties.latestRevisionName == properties.latestReadyRevisionName && properties.runningStatus == 'Running'" \
            --output tsv 2>/dev/null)"
        if [ "$ready" != true ]; then
            pending="$pending $app"
        fi
    done
    if [ -z "$pending" ]; then
        echo "  all apps running"
        break
    fi
    echo "  $(date +%H:%M:%S) waiting for:$pending"
    if [ "$attempt" = 90 ]; then
        echo "The apps did not all start within 30 minutes. See an app's logs with:" >&2
        echo "  az containerapp logs show --subscription $subscription --resource-group $group --name <app> --tail 100" >&2
        exit 1
    fi
    sleep 20
done

if [ -n "$demo_docs" ]; then
    step "6/7 Downloading and processing $demo_docs demo documents"
    "$scripts/run-job.sh" pipeline python scripts/demo/download.py \
        --limit "$demo_docs" --data-dir "/app/data/$demo_source"
    "$scripts/run-job.sh" pipeline python -m pipeline.orchestrator \
        --data-source "$demo_source" --num-records "$demo_docs" --skip-download
else
    step "6/7 No demo documents requested"
fi

step "7/7 Checking the site"
site_url="$(output site_url)"
for attempt in $(seq 1 30); do
    if curl -fsS -o /dev/null "$site_url/" && curl -fsS -o /dev/null "$site_url/api/health"; then
        break
    fi
    if [ "$attempt" = 30 ]; then
        echo "The site did not answer at $site_url" >&2
        exit 1
    fi
    sleep 10
done
echo
echo "Evidence Lab is running at $site_url"
if [ -n "$demo_docs" ]; then
    echo "Choose the dataset 'Demo Data from World Bank' to search the demo documents."
fi
echo "Remove everything with: deploy/azure/scripts/teardown.sh"
