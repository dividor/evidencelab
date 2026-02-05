#!/bin/bash
# Check Azure Batch job status and costs
#
# Usage:
#   ./check-batch-job.sh [job-id]
#   ./check-batch-job.sh --all

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Source .env file
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
BATCH_ACCOUNT_NAME="${BATCH_ACCOUNT_NAME:-evidencelabbatch}"
POOL_ID="${POOL_ID:-pipeline-pool}"

# Parse arguments
JOB_ID="$1"
SHOW_ALL=false

if [[ "$1" == "--all" ]]; then
    SHOW_ALL=true
fi

# Login to Batch account
az batch account login \
    --name "$BATCH_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" 2>/dev/null

echo "=============================================="
echo "Azure Batch Status"
echo "=============================================="

# Show pool status
echo ""
echo "=== Pool Status ==="
POOL_INFO=$(az batch pool show --pool-id "$POOL_ID" 2>/dev/null || echo "{}")
if [[ "$POOL_INFO" != "{}" ]]; then
    CURRENT_DEDICATED=$(echo "$POOL_INFO" | jq -r '.currentDedicatedNodes // 0')
    TARGET_DEDICATED=$(echo "$POOL_INFO" | jq -r '.targetDedicatedNodes // 0')
    VM_SIZE=$(echo "$POOL_INFO" | jq -r '.vmSize // "unknown"')
    POOL_STATE=$(echo "$POOL_INFO" | jq -r '.allocationState // "unknown"')
    echo "  Pool: $POOL_ID"
    echo "  VM Size: $VM_SIZE"
    echo "  Nodes: $CURRENT_DEDICATED / $TARGET_DEDICATED (current/target)"
    echo "  State: $POOL_STATE"
else
    echo "  Pool not found"
fi

# Show node status
echo ""
echo "=== Node Status ==="
NODES=$(az batch node list --pool-id "$POOL_ID" -o json 2>/dev/null || echo "[]")
NODE_COUNT=$(echo "$NODES" | jq 'length')
if [[ "$NODE_COUNT" -gt 0 ]]; then
    echo "$NODES" | jq -r '.[] | "  Node: \(.id) - State: \(.state) - IP: \(.ipAddress // "pending")"'
else
    echo "  No nodes running"
fi

# List recent jobs
echo ""
echo "=== Recent Jobs ==="
JOBS=$(az batch job list -o json 2>/dev/null || echo "[]")
echo "$JOBS" | jq -r '.[-5:] | .[] | "  \(.id): \(.state) (created: \(.creationTime[:19]))"' 2>/dev/null || echo "  No jobs found"

# Show specific job details
if [[ -n "$JOB_ID" && "$SHOW_ALL" == "false" ]]; then
    echo ""
    echo "=== Job Details: $JOB_ID ==="

    JOB_INFO=$(az batch job show --job-id "$JOB_ID" 2>/dev/null || echo "{}")
    if [[ "$JOB_INFO" != "{}" ]]; then
        JOB_STATE=$(echo "$JOB_INFO" | jq -r '.state')
        CREATED=$(echo "$JOB_INFO" | jq -r '.creationTime[:19]')
        echo "  State: $JOB_STATE"
        echo "  Created: $CREATED"

        # Show tasks summary
        echo ""
        TASKS=$(az batch task list --job-id "$JOB_ID" -o json 2>/dev/null || echo "[]")
        TASK_COUNT=$(echo "$TASKS" | jq 'length')
        RUNNING=$(echo "$TASKS" | jq '[.[] | select(.state=="running")] | length')
        COMPLETED=$(echo "$TASKS" | jq '[.[] | select(.state=="completed")] | length')
        FAILED=$(echo "$TASKS" | jq '[.[] | select(.executionInfo.exitCode != null and .executionInfo.exitCode != 0)] | length')

        echo "  Tasks: $TASK_COUNT total ($RUNNING running, $COMPLETED completed, $FAILED failed)"
        echo ""
        echo "  Task Status:"
        echo "$TASKS" | jq -r '.[] | "    \(.id): \(.state) (exit: \(.executionInfo.exitCode // "running"))"'
    else
        echo "  Job not found"
    fi
fi

# Cost estimation
echo ""
echo "=== Cost Estimation ==="
# Standard_D4s_v3: ~$0.192/hour in West US 2
# https://azure.microsoft.com/en-us/pricing/details/batch/
VM_HOURLY_RATE=0.192
CURRENT_NODES=${CURRENT_DEDICATED:-0}
if [[ "$CURRENT_NODES" -gt 0 ]]; then
    HOURLY_COST=$(echo "$CURRENT_NODES * $VM_HOURLY_RATE" | bc -l)
    printf "  Current pool cost: \$%.3f/hour (%d nodes × \$%.3f/node/hour)\n" "$HOURLY_COST" "$CURRENT_NODES" "$VM_HOURLY_RATE"
    echo "  Note: You pay for running nodes even when idle. Scale down when done:"
    echo "        az batch pool resize --pool-id $POOL_ID --target-dedicated-nodes 0"
else
    echo "  No nodes running - no compute costs"
fi
