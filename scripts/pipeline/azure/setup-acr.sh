#!/bin/bash
# Setup Azure Container Registry for Evidence Lab pipeline
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <name>)
#
# Usage:
#   ./setup-acr.sh

set -e

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-Humanitarian}"
ACR_NAME="${ACR_NAME:-evidencelabacr}"
LOCATION="${LOCATION:-westus2}"

echo "=============================================="
echo "Setting up Azure Container Registry"
echo "=============================================="
echo "Resource Group: $RESOURCE_GROUP"
echo "ACR Name: $ACR_NAME"
echo "Location: $LOCATION"
echo ""

# Check if logged in
if ! az account show &> /dev/null; then
    echo "Error: Not logged in to Azure CLI. Run 'az login' first."
    exit 1
fi

echo "Current subscription:"
az account show --query "{Name:name, ID:id}" -o table
echo ""

# Create ACR with Basic SKU (cheapest, ~$5/month)
# Resource group already exists
echo "Creating Azure Container Registry..."
az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku Basic \
    --admin-enabled true \
    --location "$LOCATION" \
    -o table

# Get ACR credentials
echo ""
echo "=============================================="
echo "ACR Created Successfully!"
echo "=============================================="
echo ""
echo "Login server: ${ACR_NAME}.azurecr.io"
echo ""
echo "To login and push images:"
echo "  az acr login --name $ACR_NAME"
echo "  docker tag evidencelab-ai-python:latest ${ACR_NAME}.azurecr.io/pipeline:latest"
echo "  docker push ${ACR_NAME}.azurecr.io/pipeline:latest"
echo ""
echo "ACR credentials (for Container Apps):"
az acr credential show --name "$ACR_NAME" --query "{Username:username, Password:passwords[0].value}" -o table
