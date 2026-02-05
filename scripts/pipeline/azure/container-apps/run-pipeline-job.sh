#!/bin/bash
# Run Evidence Lab pipeline as parallel Azure Container Apps jobs
#
# This script:
#   1. Sources .env for API keys automatically
#   2. Builds and pushes the pipeline Docker image to ACR
#   3. Creates N parallel Container Apps jobs with partition arguments
#   4. Each job processes a slice of documents with optional internal parallelism
#
# Prerequisites:
#   - Azure CLI logged in
#   - ACR and Container Apps environment created (run setup scripts first)
#   - .env file with QDRANT_API_KEY, HUGGINGFACE_API_KEY, etc.
#   - Storage mount configured in Container Apps environment
#
# Usage:
#   # 5 containers, each with 2 internal workers
#   ./run-pipeline-job.sh --jobs 5 --workers 2 --data-source uneg \
#       --num-records 1000 --skip-download --recent-first
#
#   # 10 containers, single-threaded each (lower memory)
#   ./run-pipeline-job.sh --jobs 10 --data-source uneg --skip-download
#
# Environment variables (override defaults):
#   RESOURCE_GROUP - Azure resource group (default: Humanitarian)
#   ACR_NAME - Azure Container Registry name (default: evidencelabacr)
#   ENVIRONMENT - Container Apps environment (default: evidencelab-env)
#   SKIP_BUILD - Set to "true" to skip Docker build/push

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source .env file for API keys
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo "Loading environment from .env..."
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "Warning: .env file not found at $PROJECT_ROOT/.env"
fi

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
ACR_NAME="${ACR_NAME:-evidencelabacr}"
ENVIRONMENT="${ENVIRONMENT:-evidencelab-env}"
LOCATION="${LOCATION:-westus2}"
# External Qdrant URL - direct port access (no HTTPS, Qdrant handles auth)
QDRANT_EXTERNAL_HOST="${QDRANT_EXTERNAL_HOST:-http://evidencelab.ai:6333}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
JOB_PREFIX="pipeline-job"
STORAGE_MOUNT_NAME="${STORAGE_MOUNT_NAME:-evaluationdata}"

# Parse arguments
JOBS=1
WORKERS=1
ORCHESTRATOR_ARGS=""
SKIP_BUILD="${SKIP_BUILD:-false}"

print_usage() {
    echo "Usage: $0 --jobs N [--workers M] [orchestrator options]"
    echo ""
    echo "Options:"
    echo "  --jobs N          Number of Container Apps instances (partitions)"
    echo "  --workers M       Number of workers within each container (default: 1)"
    echo "  --skip-build      Skip Docker build and push"
    echo ""
    echo "Orchestrator options (passed through):"
    echo "  --data-source     Data source name (required, e.g., 'uneg')"
    echo "  --num-records     Maximum documents to process"
    echo "  --skip-download   Skip download step"
    echo "  --skip-scan       Skip scan step"
    echo "  --skip-parse      Skip parse step"
    echo "  --skip-summarize  Skip summarize step"
    echo "  --skip-index      Skip index step"
    echo "  --recent-first    Process recent documents first"
    echo ""
    echo "Examples:"
    echo "  $0 --jobs 5 --workers 2 --data-source uneg --skip-download --recent-first"
    echo "  $0 --jobs 10 --data-source uneg --num-records 500 --skip-download"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD="true"
            shift
            ;;
        --help|-h)
            print_usage
            exit 0
            ;;
        *)
            # Pass all other arguments to orchestrator
            ORCHESTRATOR_ARGS="$ORCHESTRATOR_ARGS $1"
            shift
            ;;
    esac
done

echo "=============================================="
echo "Evidence Lab Pipeline - Azure Container Apps"
echo "=============================================="
echo "Jobs (partitions): $JOBS"
echo "Workers per job: $WORKERS"
echo "Orchestrator args: $ORCHESTRATOR_ARGS"
echo "ACR: ${ACR_NAME}.azurecr.io"
echo "Environment: $ENVIRONMENT"
echo "Qdrant Host: $QDRANT_EXTERNAL_HOST"
echo "Storage Mount: $STORAGE_MOUNT_NAME"
echo ""

# Check required environment variables
if [[ -z "$QDRANT_API_KEY" ]]; then
    echo "Error: QDRANT_API_KEY not found in .env or environment"
    exit 1
fi

if [[ -z "$HUGGINGFACE_API_KEY" ]] && [[ -z "$NOVITA_API_KEY" ]]; then
    echo "Warning: Neither HUGGINGFACE_API_KEY nor NOVITA_API_KEY is set"
    echo "LLM summarization may fail"
fi

# Check if logged in to Azure
if ! az account show &> /dev/null; then
    echo "Error: Not logged in to Azure CLI. Run 'az login' first."
    exit 1
fi

# Build and push Docker image
if [[ "$SKIP_BUILD" != "true" ]]; then
    echo "Building and pushing Docker image..."
    cd "$PROJECT_ROOT"

    az acr login --name "$ACR_NAME"

    # Build the pipeline image
    docker build -t "${ACR_NAME}.azurecr.io/pipeline:${IMAGE_TAG}" \
        --target runtime \
        -f Dockerfile .

    docker push "${ACR_NAME}.azurecr.io/pipeline:${IMAGE_TAG}"
    echo "Image pushed: ${ACR_NAME}.azurecr.io/pipeline:${IMAGE_TAG}"
else
    echo "Skipping Docker build (--skip-build or SKIP_BUILD=true)"
fi

# Get ACR credentials
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query "username" -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

echo ""
echo "Creating $JOBS parallel jobs..."
echo ""

# Create jobs for each partition
JOB_NAMES=""
TIMESTAMP=$(date +%H%M%S)

for i in $(seq 1 $JOBS); do
    # Name must be <32 chars, lowercase, alphanumeric and hyphens only
    JOB_NAME="pipe-${i}of${JOBS}-${TIMESTAMP}"

    echo "Creating job $i/$JOBS: $JOB_NAME"

    # Create symlink from ./data to /mnt/data (Azure Files mount)
    # This allows the pipeline to use relative paths stored in the database
    FULL_CMD="ln -sf /mnt/data /app/data && python -m pipeline.orchestrator --partition ${i}/${JOBS} --workers ${WORKERS} ${ORCHESTRATOR_ARGS}"

    # Create job without command override first
    az containerapp job create \
        --name "$JOB_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --trigger-type Manual \
        --replica-timeout 14400 \
        --replica-retry-limit 1 \
        --replica-completion-count 1 \
        --parallelism 1 \
        --image "${ACR_NAME}.azurecr.io/pipeline:${IMAGE_TAG}" \
        --registry-server "${ACR_NAME}.azurecr.io" \
        --registry-username "$ACR_USERNAME" \
        --registry-password "$ACR_PASSWORD" \
        --cpu 4 \
        --memory 8Gi \
        --env-vars \
            "QDRANT_HOST=$QDRANT_EXTERNAL_HOST" \
            "QDRANT_API_KEY=$QDRANT_API_KEY" \
            "HUGGINGFACE_API_KEY=${HUGGINGFACE_API_KEY:-}" \
            "NOVITA_API_KEY=${NOVITA_API_KEY:-}" \
            "DATA_MOUNT_PATH=/mnt/data" \
            "PYTHONPATH=/app" \
        -o table

    # Update job with command using YAML (include all settings to avoid overwrite)
    JOB_YAML=$(mktemp)
    cat > "$JOB_YAML" << EOFYAML
properties:
  template:
    volumes:
      - name: data-volume
        storageName: ${STORAGE_MOUNT_NAME}
        storageType: AzureFile
    containers:
      - name: pipeline
        image: ${ACR_NAME}.azurecr.io/pipeline:${IMAGE_TAG}
        resources:
          cpu: 4
          memory: 8Gi
        volumeMounts:
          - volumeName: data-volume
            mountPath: /mnt/data
        env:
          - name: QDRANT_HOST
            value: "${QDRANT_EXTERNAL_HOST}"
          - name: QDRANT_API_KEY
            value: "${QDRANT_API_KEY}"
          - name: HUGGINGFACE_API_KEY
            value: "${HUGGINGFACE_API_KEY:-}"
          - name: NOVITA_API_KEY
            value: "${NOVITA_API_KEY:-}"
          - name: DATA_MOUNT_PATH
            value: "/mnt/data"
          - name: PYTHONPATH
            value: "/app"
        command:
          - /bin/sh
          - -c
          - "${FULL_CMD}"
EOFYAML

    az containerapp job update \
        --name "$JOB_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --yaml "$JOB_YAML" \
        -o table

    rm -f "$JOB_YAML"

    # Note: Storage mount is configured at environment level
    # The job will access it at the mount path configured in setup-container-apps.sh

    # Start the job
    echo "Starting job execution..."
    az containerapp job start \
        --name "$JOB_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        -o table

    JOB_NAMES="$JOB_NAMES $JOB_NAME"
    echo ""
done

echo "=============================================="
echo "All $JOBS jobs submitted!"
echo "=============================================="
echo ""
echo "Jobs created:"
for name in $JOB_NAMES; do
    echo "  - $name"
done
echo ""
echo "To monitor jobs:"
echo "  az containerapp job execution list --name <job-name> --resource-group $RESOURCE_GROUP -o table"
echo ""
echo "To view logs:"
echo "  az containerapp logs show --name <job-name> --resource-group $RESOURCE_GROUP --type console"
echo ""
echo "To delete all jobs when complete:"
echo "  for name in $JOB_NAMES; do"
echo "    az containerapp job delete --name \$name --resource-group $RESOURCE_GROUP --yes"
echo "  done"
