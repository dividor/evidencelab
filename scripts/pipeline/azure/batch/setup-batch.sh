#!/bin/bash
# Setup Azure Batch account and pool for pipeline processing
#
# Prerequisites:
#   - Azure CLI logged in
#   - ACR already created (run ../setup-acr.sh first)
#   - Azure Files storage account exists
#   - Batch quotas: Pool >= 1, DSv3 Series >= 4 vCPUs
#
# Usage:
#   export STORAGE_ACCOUNT_NAME=vmstprod01
#   export FILES_SHARE_NAME=evaluation-db
#   ./setup-batch.sh

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Source .env file for configuration
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo "Loading environment from .env..."
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
LOCATION="${LOCATION:-westus2}"
BATCH_ACCOUNT_NAME="${BATCH_ACCOUNT_NAME:-evidencelabbatch}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-vmstprod01}"
FILES_SHARE_NAME="${FILES_SHARE_NAME:-evaluation-db}"
ACR_NAME="${ACR_NAME:-evidencelabacr}"
POOL_ID="${POOL_ID:-pipeline-pool}"
VM_SIZE="${VM_SIZE:-Standard_D4s_v3}"  # 4 vCPUs, 16GB RAM

echo "=============================================="
echo "Azure Batch Setup"
echo "=============================================="
echo "Resource Group: $RESOURCE_GROUP"
echo "Location: $LOCATION"
echo "Batch Account: $BATCH_ACCOUNT_NAME"
echo "Storage Account: $STORAGE_ACCOUNT_NAME"
echo "Files Share: $FILES_SHARE_NAME"
echo "ACR: $ACR_NAME"
echo "Pool ID: $POOL_ID"
echo "VM Size: $VM_SIZE"
echo ""

# Step 1: Create Batch account if not exists
echo "Step 1: Creating Batch account..."
if az batch account show --name "$BATCH_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    echo "  Batch account already exists"
else
    az batch account create \
        --name "$BATCH_ACCOUNT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION"
    echo "  ✓ Batch account created"
fi

# Step 2: Get credentials
echo ""
echo "Step 2: Getting credentials..."

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
ACR_SERVER="${ACR_NAME}.azurecr.io"
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query "username" -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)
STORAGE_KEY=$(az storage account keys list \
    --account-name "$STORAGE_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].value" -o tsv)

echo "  ✓ Subscription: $SUBSCRIPTION_ID"
echo "  ✓ ACR server: $ACR_SERVER"
echo "  ✓ Storage account: $STORAGE_ACCOUNT_NAME"

# Login to Batch account
az batch account login \
    --name "$BATCH_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP"

# Step 3: Delete existing pool if exists
echo ""
echo "Step 3: Checking for existing pool..."
if az batch pool show --pool-id "$POOL_ID" &>/dev/null; then
    echo "  Pool exists, deleting..."
    az batch pool delete --pool-id "$POOL_ID" --yes
    echo "  Waiting for deletion..."
    while az batch pool show --pool-id "$POOL_ID" &>/dev/null; do
        sleep 5
    done
    echo "  ✓ Pool deleted"
else
    echo "  No existing pool"
fi

# Step 4: Create pool with container and mount support via ARM API
# The az batch CLI doesn't support all pool options, so we use REST API
echo ""
echo "Step 4: Creating pool with container and mount support..."

az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Batch/batchAccounts/${BATCH_ACCOUNT_NAME}/pools/${POOL_ID}?api-version=2024-02-01" \
  --body "{
    \"properties\": {
      \"vmSize\": \"${VM_SIZE}\",
      \"deploymentConfiguration\": {
        \"virtualMachineConfiguration\": {
          \"imageReference\": {
            \"publisher\": \"microsoft-azure-batch\",
            \"offer\": \"ubuntu-server-container\",
            \"sku\": \"20-04-lts\"
          },
          \"nodeAgentSkuId\": \"batch.node.ubuntu 20.04\",
          \"containerConfiguration\": {
            \"type\": \"DockerCompatible\",
            \"containerImageNames\": [
              \"${ACR_SERVER}/pipeline:latest\"
            ],
            \"containerRegistries\": [
              {
                \"registryServer\": \"${ACR_SERVER}\",
                \"userName\": \"${ACR_USERNAME}\",
                \"password\": \"${ACR_PASSWORD}\"
              }
            ]
          }
        }
      },
      \"mountConfiguration\": [
        {
          \"azureFileShareConfiguration\": {
            \"accountName\": \"${STORAGE_ACCOUNT_NAME}\",
            \"azureFileUrl\": \"https://${STORAGE_ACCOUNT_NAME}.file.core.windows.net/${FILES_SHARE_NAME}\",
            \"accountKey\": \"${STORAGE_KEY}\",
            \"relativeMountPath\": \"files\",
            \"mountOptions\": \"-o vers=3.0,dir_mode=0777,file_mode=0777,sec=ntlmssp\"
          }
        }
      ],
      \"scaleSettings\": {
        \"fixedScale\": {
          \"targetDedicatedNodes\": 0
        }
      }
    }
  }" --output none

echo "  ✓ Pool created: $POOL_ID"

echo ""
echo "=============================================="
echo "Azure Batch Setup Complete!"
echo "=============================================="
echo ""
echo "Pool: $POOL_ID"
echo "VM Size: $VM_SIZE (4 vCPUs, 16GB RAM)"
echo "Container: ${ACR_SERVER}/pipeline:latest"
echo "Mount: /mnt/batch/tasks/fsmounts/files -> Azure Files (${FILES_SHARE_NAME})"
echo ""
echo "To run a job: ./run-batch-job.sh --data-source uneg --skip-download"
echo "To check status: ./check-batch-job.sh"
