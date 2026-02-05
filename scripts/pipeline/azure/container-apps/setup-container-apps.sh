#!/bin/bash
# Setup Azure Container Apps environment for Evidence Lab pipeline
#
# Prerequisites:
#   - Azure CLI installed and logged in
#   - ACR created (run setup-acr.sh first)
#   - Container Apps extension installed
#
# Usage:
#   ./setup-container-apps.sh
#
# Environment variables (optional overrides):
#   STORAGE_ACCOUNT_NAME - Azure Storage account name
#   STORAGE_SHARE_NAME - Azure Files share name
#   STORAGE_ACCOUNT_KEY - Storage account key

set -e

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
LOCATION="${LOCATION:-westus2}"
ENVIRONMENT="${ENVIRONMENT:-evidencelab-env}"
ACR_NAME="${ACR_NAME:-evidencelabacr}"

# Storage configuration (Azure Files share, mounted on VM at /mnt/files/evaluation-db/)
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-}"
STORAGE_SHARE_NAME="${STORAGE_SHARE_NAME:-}"
STORAGE_ACCOUNT_KEY="${STORAGE_ACCOUNT_KEY:-}"

echo "=============================================="
echo "Setting up Azure Container Apps Environment"
echo "=============================================="
echo "Resource Group: $RESOURCE_GROUP"
echo "Environment: $ENVIRONMENT"
echo "Location: $LOCATION"
echo ""

# Check if logged in
if ! az account show &> /dev/null; then
    echo "Error: Not logged in to Azure CLI. Run 'az login' first."
    exit 1
fi

# Install/upgrade containerapp extension
echo "Ensuring Container Apps extension is installed..."
az extension add --name containerapp --upgrade --yes 2>/dev/null || true

# Register required providers
echo "Registering required resource providers..."
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

# Create Container Apps environment (Consumption tier - pay per use)
echo ""
echo "Creating Container Apps environment..."
az containerapp env create \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    -o table

# Configure Azure Files storage mount if credentials provided
if [[ -n "$STORAGE_ACCOUNT_NAME" && -n "$STORAGE_SHARE_NAME" && -n "$STORAGE_ACCOUNT_KEY" ]]; then
    echo ""
    echo "Configuring Azure Files storage mount..."
    az containerapp env storage set \
        --name "$ENVIRONMENT" \
        --resource-group "$RESOURCE_GROUP" \
        --storage-name evaluationdata \
        --azure-file-account-name "$STORAGE_ACCOUNT_NAME" \
        --azure-file-share-name "$STORAGE_SHARE_NAME" \
        --azure-file-account-key "$STORAGE_ACCOUNT_KEY" \
        --access-mode ReadWrite \
        -o table
    echo "Storage mount configured: evaluationdata"
else
    echo ""
    echo "WARNING: Storage mount not configured."
    echo "To add storage mount later, run:"
    echo "  az containerapp env storage set \\"
    echo "    --name $ENVIRONMENT \\"
    echo "    --resource-group $RESOURCE_GROUP \\"
    echo "    --storage-name evaluationdata \\"
    echo "    --azure-file-account-name <account> \\"
    echo "    --azure-file-share-name <share> \\"
    echo "    --azure-file-account-key <key> \\"
    echo "    --access-mode ReadWrite"
fi

echo ""
echo "=============================================="
echo "Container Apps Environment Created!"
echo "=============================================="
echo ""
echo "Environment: $ENVIRONMENT"
echo "Resource Group: $RESOURCE_GROUP"
echo ""
echo "Next steps:"
echo "  1. Configure storage mount (if not done above)"
echo "  2. Build and push Docker image to ACR"
echo "  3. Run pipeline jobs with run-pipeline-job.sh"
echo ""
echo "To view environment:"
echo "  az containerapp env show --name $ENVIRONMENT --resource-group $RESOURCE_GROUP"
