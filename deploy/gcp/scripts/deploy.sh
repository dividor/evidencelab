#!/usr/bin/env bash
# Deploy Evidence Lab to Google Cloud Run, end to end.
#
# Usage: deploy/gcp/scripts/deploy.sh [--demo DOCS] [--yes]
#
#   --demo DOCS  Also download and process DOCS World Bank demo documents,
#                with the demo data source from scripts/demo/run_demo.py and
#                the Vertex AI models, which the containers call as their
#                service account. The site is then usable without signing in:
#                the web app is built with the API key (anonymous_access).
#   --yes        Apply Terraform changes without asking first.
#
# Steps:
#   1. enable the Cloud Resource Manager API, which Terraform needs before it
#      can read the project, then terraform apply: the other APIs, network,
#      database, Redis, bucket, Qdrant, secrets, image registry and jobs
#   2. build the web app image and push it to the registry
#   3. run the migrate job
#   4. create or update the web and embedding services
#   5. wait until the services are running
#   6. with --demo, download and process the demo documents
#   7. check the site answers, and print its address
#
# Run it again to upgrade: it applies changes, builds a new web app image,
# migrates, then moves the services to new revisions. Reads terraform.tfvars
# in deploy/gcp. Needs terraform, docker (with buildx), gcloud, python3 and
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
    echo "No deploy/gcp/terraform.tfvars. Copy terraform.tfvars.example and fill it in." >&2
    exit 1
fi

# With --demo, the deployment runs a config.json with the demo data source and
# the Vertex AI models, written by deploy/demo_config.py.
deploy_vars=()
if [ -n "$demo_docs" ]; then
    step "Writing the demo configuration"
    python3 "$here/../demo_config.py" --provider google_vertex --out-dir "$here/.demo"
    demo_source="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["data_source"])' "$here/.demo/demo.json")"
    deploy_vars=(-var "config_json_path=.demo/config.json" -var "anonymous_access=true")
fi

# Terraform reads the project before it can enable APIs, which needs this one.
project="$(python3 -c '
import re, sys
match = re.search(r"^\s*project_id\s*=\s*\"([^\"]+)\"", open(sys.argv[1]).read(), re.M)
sys.exit("Set project_id in deploy/gcp/terraform.tfvars.") if not match else print(match.group(1))
' "$here/terraform.tfvars")"
gcloud services enable cloudresourcemanager.googleapis.com --project "$project"

$tf -chdir="$here" init -input=false >/dev/null

# Keep the services as they are on this first apply: running the current web app
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

region="$(output region)"

step "2/7 Building and pushing the web app image"
ui_tag="$(date -u +%Y%m%d%H%M%S)"
"$scripts/build-ui-image.sh" "$ui_tag"

step "3/7 Running the database migrations"
"$scripts/run-job.sh" migrate

step "4/7 Creating or updating the services"
$tf -chdir="$here" apply -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${deploy_vars[@]+"${deploy_vars[@]}"} \
    -var "services_enabled=true" -var "ui_image_tag=$ui_tag"

step "5/7 Waiting for the services"
services="$($tf -chdir="$here" output -json services | python3 -c 'import json, sys; print(" ".join(json.load(sys.stdin)))')"
for attempt in $(seq 1 90); do
    pending=""
    for service in $services; do
        revisions="$(gcloud run services describe "$service" --project "$project" --region "$region" \
            --format 'value(status.latestCreatedRevisionName, status.latestReadyRevisionName)')"
        if [ "$(echo "$revisions" | awk '{print ($1 == $2 && $1 != "")}')" != 1 ]; then
            pending="$pending $service"
        fi
    done
    if [ -z "$pending" ]; then
        echo "  all services running"
        break
    fi
    echo "  $(date +%H:%M:%S) waiting for:$pending"
    if [ "$attempt" = 90 ]; then
        echo "The services did not all start within 30 minutes. See a service's logs with:" >&2
        echo "  gcloud run services logs read <service> --project $project --region $region --limit 100" >&2
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
echo "Remove everything with: deploy/gcp/scripts/teardown.sh"
