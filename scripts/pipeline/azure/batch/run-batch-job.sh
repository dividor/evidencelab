#!/bin/bash
# Run pipeline as parallel Azure Batch jobs
#
# This script:
#   1. Sources .env for API keys
#   2. Scales pool to requested number of nodes (VMs)
#   3. Creates N parallel tasks with partition arguments
#
# PARALLELISM EXPLAINED:
#   - Node  = 1 VM (Standard_D4s_v3: 4 vCPUs, 16GB RAM, ~$0.19/hr)
#   - Job   = Number of partitions (tasks). Each task gets 1/N of documents.
#   - Worker = Parallel threads WITHIN each task for document processing.
#
#   Total parallelism = nodes × workers (since 1 task runs per node at a time)
#
#   Example: --nodes 10 --jobs 10 --workers 2
#     → 10 VMs running 10 tasks (1 per VM)
#     → Each task processes its partition with 2 parallel workers
#     → 20 documents processing simultaneously
#
# Prerequisites:
#   - Pool created via ./setup-batch.sh
#   - .env file with QDRANT_API_KEY, HUGGINGFACE_API_KEY
#
# Usage:
#   # 10 VMs, 10 partitions, 2 workers each = 20 parallel doc processors
#   ./run-batch-job.sh --jobs 10 --nodes 10 --workers 2 --data-source uneg --skip-download --recent-first
#
#   # Budget option: 5 VMs, 10 partitions (5 run, 5 queue), 2 workers each
#   ./run-batch-job.sh --jobs 10 --nodes 5 --workers 2 --data-source uneg --skip-download --recent-first
#
#   # Single task (default)
#   ./run-batch-job.sh --data-source uneg --skip-download

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Source .env file
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo "Loading environment from .env..."
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
BATCH_ACCOUNT_NAME="${BATCH_ACCOUNT_NAME:-evidencelabbatch}"
ACR_NAME="${ACR_NAME:-evidencelabacr}"
ACR_SERVER="${ACR_NAME}.azurecr.io"
POOL_ID="${POOL_ID:-pipeline-pool}"
QDRANT_EXTERNAL_HOST="${QDRANT_EXTERNAL_HOST:-http://evidencelab.ai:6333}"

# Parse arguments
JOBS=1
NODES=1
WORKERS=1
ORCHESTRATOR_ARGS=""

print_usage() {
    echo "Usage: $0 --jobs N --nodes M [--workers W] [orchestrator options]"
    echo ""
    echo "PARALLELISM OPTIONS:"
    echo "  --nodes N         Number of VMs to run (each ~\$0.19/hr)"
    echo "  --jobs N          Number of partitions. Documents split into N parts."
    echo "                    Tip: Set jobs >= nodes so each VM has work."
    echo "  --workers W       Parallel workers per task (default: 1)"
    echo "                    Each VM runs 1 task with W parallel doc processors."
    echo ""
    echo "  Total parallelism = nodes × workers"
    echo "  Example: --nodes 10 --workers 2 = 20 docs processing at once"
    echo ""
    echo "ORCHESTRATOR OPTIONS (passed through):"
    echo "  --data-source     Data source name (required, e.g., 'uneg')"
    echo "  --num-records     Maximum documents to process per partition"
    echo "  --skip-download   Skip download step"
    echo "  --skip-scan       Skip scan step"
    echo "  --skip-parse      Skip parse step"
    echo "  --skip-summarize  Skip summarize step"
    echo "  --skip-index      Skip index step"
    echo "  --recent-first    Process recent documents first (applied before partitioning)"
    echo ""
    echo "EXAMPLES:"
    echo "  # 10 VMs, 2 workers each = 20 parallel processors (~\$23/12hrs)"
    echo "  $0 --jobs 10 --nodes 10 --workers 2 --data-source uneg --skip-download --skip-scan --recent-first"
    echo ""
    echo "  # Budget: 5 VMs, tasks queue (~\$11.50/12hrs)"
    echo "  $0 --jobs 10 --nodes 5 --workers 2 --data-source uneg --skip-download --skip-scan--recent-first"
    echo ""
    echo "COST: ~\$0.19/node/hour. Don't forget to scale down when done:"
    echo "  az batch pool resize --pool-id $POOL_ID --target-dedicated-nodes 0"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        --nodes)
            NODES="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --help|-h)
            print_usage
            exit 0
            ;;
        *)
            ORCHESTRATOR_ARGS="$ORCHESTRATOR_ARGS $1"
            shift
            ;;
    esac
done

# Validate required env vars
if [[ -z "$QDRANT_API_KEY" ]]; then
    echo "Error: QDRANT_API_KEY not found in .env"
    exit 1
fi

# Generate job ID with timestamp
JOB_ID="pipeline-$(date +%Y%m%d-%H%M%S)"

echo "=============================================="
echo "Azure Batch Job Submission"
echo "=============================================="
echo "Job ID: $JOB_ID"
echo "Pool: $POOL_ID"
echo "Nodes: $NODES"
echo "Parallel tasks: $JOBS"
echo "Workers per task: $WORKERS"
echo "Orchestrator args:$ORCHESTRATOR_ARGS"
echo ""

# Login to Batch account
echo "Logging into Batch account..."
az batch account login \
    --name "$BATCH_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP"

# Check pool exists
if ! az batch pool show --pool-id "$POOL_ID" &>/dev/null; then
    echo "Error: Pool '$POOL_ID' not found. Run ./setup-batch.sh first."
    exit 1
fi

# Scale up the pool
echo ""
echo "Scaling pool to $NODES nodes..."
az batch pool resize \
    --pool-id "$POOL_ID" \
    --target-dedicated-nodes "$NODES" \
    --target-low-priority-nodes 0

echo "Waiting for nodes to be ready (2-5 minutes per node)..."
while true; do
    IDLE_COUNT=$(az batch node list --pool-id "$POOL_ID" --query "length([?state=='idle'])" -o tsv 2>/dev/null || echo "0")
    TOTAL_COUNT=$(az batch node list --pool-id "$POOL_ID" --query "length(@)" -o tsv 2>/dev/null || echo "0")

    if [[ "$IDLE_COUNT" -ge "$NODES" ]]; then
        echo "  ✓ All $NODES nodes ready"
        break
    else
        echo "  Nodes ready: $IDLE_COUNT / $NODES (total provisioned: $TOTAL_COUNT)"
    fi
    sleep 15
done

# Create job
echo ""
echo "Creating job..."
az batch job create \
    --id "$JOB_ID" \
    --pool-id "$POOL_ID" 2>/dev/null || echo "  Job may already exist, continuing..."

# Create tasks with partition settings
echo ""
echo "Creating $JOBS parallel tasks..."

# Container run options with environment variables and volume mount
CONTAINER_OPTS="--rm"
CONTAINER_OPTS="$CONTAINER_OPTS -e DATA_MOUNT_PATH=/mnt/files"
CONTAINER_OPTS="$CONTAINER_OPTS -e QDRANT_HOST=$QDRANT_EXTERNAL_HOST"
CONTAINER_OPTS="$CONTAINER_OPTS"
CONTAINER_OPTS="$CONTAINER_OPTS -e QDRANT_API_KEY=$QDRANT_API_KEY"
CONTAINER_OPTS="$CONTAINER_OPTS -e HUGGINGFACE_API_KEY=${HUGGINGFACE_API_KEY:-}"
CONTAINER_OPTS="$CONTAINER_OPTS -e NOVITA_API_KEY=${NOVITA_API_KEY:-}"
# Vector config MUST be set - no defaults to avoid schema mismatches
CONTAINER_OPTS="$CONTAINER_OPTS -e DENSE_EMBEDDING_MODEL=${DENSE_EMBEDDING_MODEL:?DENSE_EMBEDDING_MODEL must be set}"
CONTAINER_OPTS="$CONTAINER_OPTS -e DENSE_VECTOR_SIZE=${DENSE_VECTOR_SIZE:?DENSE_VECTOR_SIZE must be set}"
CONTAINER_OPTS="$CONTAINER_OPTS -e PARSE_USE_SUBPROCESS=false"
CONTAINER_OPTS="$CONTAINER_OPTS -v /mnt/batch/tasks/fsmounts/files:/mnt/files"

for i in $(seq 1 $JOBS); do
    TASK_ID="task-$i"
    COMMAND_LINE="python -m pipeline.orchestrator$ORCHESTRATOR_ARGS --partition $i/$JOBS --workers $WORKERS"

    TASK_CONFIG=$(cat <<EOF
{
    "id": "$TASK_ID",
    "commandLine": "$COMMAND_LINE",
    "containerSettings": {
        "imageName": "${ACR_SERVER}/pipeline:latest",
        "containerRunOptions": "$CONTAINER_OPTS"
    },
    "userIdentity": {
        "autoUser": {
            "scope": "pool",
            "elevationLevel": "admin"
        }
    }
}
EOF
)

    echo "$TASK_CONFIG" > /tmp/batch-task-config.json
    az batch task create \
        --job-id "$JOB_ID" \
        --json-file /tmp/batch-task-config.json --output none
    rm /tmp/batch-task-config.json
    echo "  ✓ Created task $i/$JOBS (partition $i/$JOBS)"
done

echo ""
echo "=============================================="
echo "Job Submitted!"
echo "=============================================="
echo ""
echo "Job ID: $JOB_ID"
echo "Tasks: $JOBS"
echo "Nodes: $NODES"
echo ""
echo "Monitor: ./check-batch-job.sh $JOB_ID"
echo ""
echo "When done, scale down (stop billing):"
echo "  az batch pool resize --pool-id $POOL_ID --target-dedicated-nodes 0"
