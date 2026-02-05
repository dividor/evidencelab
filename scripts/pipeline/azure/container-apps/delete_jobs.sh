#!/bin/bash
# Delete all pipeline jobs

RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"

# Get all job names
JOBS=$(az containerapp job list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null)

if [ -z "$JOBS" ]; then
    echo "No jobs found in resource group: $RESOURCE_GROUP"
    exit 0
fi

echo "Jobs to delete:"
echo "$JOBS" | sed 's/^/  - /'
echo ""

# Check for --yes flag
if [ "$1" != "--yes" ] && [ "$1" != "-y" ]; then
    read -p "Delete all jobs? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo "Deleting jobs..."

# Delete in parallel
for JOB in $JOBS; do
    echo "  Deleting: $JOB"
    az containerapp job delete --name "$JOB" --resource-group "$RESOURCE_GROUP" --yes 2>/dev/null &
done

# Wait for all deletions to complete
wait

echo ""
echo "All jobs deleted."
