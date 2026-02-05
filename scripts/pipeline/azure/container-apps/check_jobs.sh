#!/bin/bash
# Check status and logs of all pipeline jobs
#
# Usage:
#   ./check_jobs.sh           # Show all jobs
#   ./check_jobs.sh --last    # Show only the most recent batch

RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
SHOW_LAST_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --last|-l)
            SHOW_LAST_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--last]"
            exit 1
            ;;
    esac
done

# Get all job names
ALL_JOBS=$(az containerapp job list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null | grep "^pipe-")

if [ -z "$ALL_JOBS" ]; then
    echo "No pipeline jobs found in resource group: $RESOURCE_GROUP"
    exit 0
fi

# Filter to last batch if requested
if [ "$SHOW_LAST_ONLY" = true ]; then
    # Extract timestamps from job names (format: pipe-Nof5-HHMMSS)
    # Get the most recent timestamp
    LATEST_TS=$(echo "$ALL_JOBS" | sed 's/.*-//' | sort -rn | head -1)

    if [ -n "$LATEST_TS" ]; then
        JOBS=$(echo "$ALL_JOBS" | grep "\-${LATEST_TS}$")
        echo "Showing jobs from batch: $LATEST_TS"
    else
        JOBS="$ALL_JOBS"
    fi
else
    JOBS="$ALL_JOBS"
fi

echo "=============================================="
echo "Pipeline Jobs Status"
echo "=============================================="
echo ""

# Quick status summary first
echo "=== Quick Status ==="
for JOB in $JOBS; do
    EXEC_INFO=$(az containerapp job execution list --name "$JOB" --resource-group "$RESOURCE_GROUP" -o json 2>/dev/null)
    if [ -n "$EXEC_INFO" ] && [ "$EXEC_INFO" != "[]" ]; then
        STATUS=$(echo "$EXEC_INFO" | jq -r '.[0].properties.status // "Unknown"')
        echo "  $JOB: $STATUS"
    else
        echo "  $JOB: No executions"
    fi
done

echo ""
echo "----------------------------------------------"
echo ""

# Detailed logs for each job
for JOB in $JOBS; do
    echo "=== $JOB ==="

    # Get execution status
    EXEC_INFO=$(az containerapp job execution list --name "$JOB" --resource-group "$RESOURCE_GROUP" -o json 2>/dev/null)

    if [ -n "$EXEC_INFO" ] && [ "$EXEC_INFO" != "[]" ]; then
        STATUS=$(echo "$EXEC_INFO" | jq -r '.[0].properties.status // "Unknown"')
        START=$(echo "$EXEC_INFO" | jq -r '.[0].properties.startTime // "Unknown"')

        echo "Status: $STATUS"
        echo "Started: $START"
        echo ""
        echo "Recent logs:"
        echo "------------"

        # Get last 15 lines of logs
        az containerapp job logs show \
            --name "$JOB" \
            --resource-group "$RESOURCE_GROUP" \
            --container pipeline 2>/dev/null | \
            grep -v "^WARNING" | \
            tail -15 | \
            jq -r '.Log // .' 2>/dev/null || echo "(no logs yet)"
    else
        echo "Status: No executions found"
    fi

    echo ""
    echo "----------------------------------------------"
    echo ""
done

# Summary
echo "=============================================="
echo "Summary"
echo "=============================================="
if [ "$SHOW_LAST_ONLY" = true ]; then
    echo "$JOBS" | wc -l | xargs echo "Jobs in batch:"
fi
az containerapp job list --resource-group "$RESOURCE_GROUP" -o table 2>/dev/null | grep -E "^(Name|pipe-.*${LATEST_TS}|---)"
