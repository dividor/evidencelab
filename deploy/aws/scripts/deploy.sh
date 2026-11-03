#!/usr/bin/env bash
# Deploy Evidence Lab to AWS, end to end.
#
# Usage: deploy/aws/scripts/deploy.sh [--demo DOCS] [--provider NAME] [--yes]
#
#   --demo DOCS      Also download and process DOCS World Bank demo documents,
#                    with the demo data source from scripts/demo/run_demo.py.
#                    The site is then usable without signing in: the web app
#                    is built with the API key (anonymous_access).
#   --provider NAME  Model provider for --demo: azure_foundry (default) or
#                    huggingface. Its keys must be set in your environment
#                    (azure_foundry: AZURE_FOUNDRY_KEY and AZURE_FOUNDRY_ENDPOINT;
#                    huggingface: HUGGINGFACE_API_KEY).
#   --yes            Apply Terraform changes without asking first.
#
# Steps:
#   1. terraform apply: network, database, Redis, file share, Qdrant, image
#      registry, load balancer and ECS cluster
#   2. copy the model provider keys from your environment into Secrets Manager
#   3. build the web app image and push it to ECR
#   4. run the migrate task
#   5. start the services and wait until they are running
#   6. with --demo, download and process the demo documents
#   7. check the site answers, and print its address
#
# Run it again to upgrade: it applies changes, rebuilds the web app image,
# migrates, then rolls the services. Reads terraform.tfvars in deploy/aws.
# Needs terraform, docker (with buildx), the aws CLI, python3 and curl. Set
# AWS_PROFILE to pick the AWS account, and TERRAFORM to run terraform some
# other way.
set -euo pipefail

demo_docs=""
provider="azure_foundry"
auto_approve=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --demo) demo_docs="${2:?--demo needs a number of documents}"; shift 2 ;;
        --provider) provider="${2:?--provider needs a name}"; shift 2 ;;
        --yes) auto_approve=(-auto-approve); shift ;;
        *) echo "usage: deploy.sh [--demo DOCS] [--provider NAME] [--yes]" >&2; exit 2 ;;
    esac
done
case "$provider" in
    azure_foundry | huggingface) ;;
    *)
        echo "--provider must be azure_foundry or huggingface. ($provider needs credentials this example cannot pass to the containers.)" >&2
        exit 2
        ;;
esac

here="$(cd "$(dirname "$0")/.." && pwd)"
scripts="$here/scripts"
tf="${TERRAFORM:-terraform}"
output() { $tf -chdir="$here" output -raw "$1"; }
step() { printf '\n==> %s\n' "$*"; }

if [ ! -f "$here/terraform.tfvars" ]; then
    echo "No deploy/aws/terraform.tfvars. Copy terraform.tfvars.example and fill it in." >&2
    exit 1
fi

# With --demo, the deployment runs a config.json with the demo data source and
# the chosen provider's models, written by demo_config.py.
deploy_vars=()
if [ -n "$demo_docs" ]; then
    step "Writing the demo configuration ($provider)"
    python3 "$scripts/demo_config.py" --provider "$provider" --out-dir "$here/.demo"
    demo_source="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["data_source"])' "$here/.demo/demo.json")"
    names="$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["secret_names"]))' "$here/.demo/demo.json")"
    deploy_vars=(-var "config_json_path=.demo/config.json" -var "provider_secret_names=$names"
        -var "anonymous_access=true")
fi

$tf -chdir="$here" init -input=false >/dev/null

# Keep the services as they are on this first apply: off for a new
# deployment, running for an upgrade.
services_now="$(output services_enabled 2>/dev/null || echo false)"

step "1/7 Creating or updating the infrastructure"
$tf -chdir="$here" apply -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${deploy_vars[@]+"${deploy_vars[@]}"} -var "services_enabled=$services_now"

region="$(output region)"

step "2/7 Storing the model provider keys in Secrets Manager"
secret_file="$(mktemp)"
trap 'rm -f "$secret_file"' EXIT
chmod 600 "$secret_file"
$tf -chdir="$here" output -json provider_secret_names | python3 -c '
import json, os, sys
names = json.load(sys.stdin)
missing = [n for n in names if not os.environ.get(n)]
if missing:
    sys.exit("Set these in your environment first: " + ", ".join(missing))
json.dump({n: os.environ[n] for n in names}, open(sys.argv[1], "w"))
print("Stored: " + (", ".join(names) or "no provider keys"))
' "$secret_file"
aws secretsmanager put-secret-value --region "$region" \
    --secret-id "$(output providers_secret_id)" \
    --secret-string "file://$secret_file" >/dev/null

step "3/7 Building and pushing the web app image"
"$scripts/build-ui-image.sh"

step "4/7 Running the database migrations"
"$scripts/run-task.sh" migrate

step "5/7 Starting the services"
$tf -chdir="$here" apply -input=false ${auto_approve[@]+"${auto_approve[@]}"} \
    ${deploy_vars[@]+"${deploy_vars[@]}"} -var "services_enabled=true"
cluster="$(output cluster)"
# A new task definition only changes when its settings do; force the services
# onto the image just pushed and the new configuration.
for service in api mcp embedding ui; do
    aws ecs update-service --region "$region" --cluster "$cluster" --service "$service" \
        --force-new-deployment >/dev/null
done
echo "Waiting for the services (the api image takes several minutes to download)..."
for attempt in $(seq 1 90); do
    states="$(aws ecs describe-services --region "$region" --cluster "$cluster" \
        --services ui api mcp embedding \
        --query 'services[].[serviceName, runningCount, desiredCount, length(deployments)]' --output text)"
    pending="$(echo "$states" | awk '$2 != $3 || $4 != 1 {print $1}' | tr '\n' ' ')"
    if [ -z "$pending" ]; then
        echo "  all services running"
        break
    fi
    echo "  $(date +%H:%M:%S) waiting for: $pending"
    if [ "$attempt" = 90 ]; then
        echo "The services did not all start within 30 minutes. See their logs:" >&2
        $tf -chdir="$here" output -json log_groups >&2
        exit 1
    fi
    sleep 20
done

if [ -n "$demo_docs" ]; then
    step "6/7 Downloading and processing $demo_docs demo documents"
    "$scripts/run-task.sh" pipeline python scripts/demo/download.py \
        --limit "$demo_docs" --data-dir "/app/data/$demo_source"
    "$scripts/run-task.sh" pipeline python -m pipeline.orchestrator \
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
echo "Remove everything with: deploy/aws/scripts/teardown.sh"
