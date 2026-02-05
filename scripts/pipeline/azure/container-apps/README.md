# Azure Container Apps Pipeline

Run the Evidence Lab pipeline on Azure Container Apps for parallel document processing.

## Overview

Azure Container Apps provides:
- **Serverless** - No infrastructure management
- **Auto-scaling** - Scale to 0 when idle
- **GPU support** - A100 available in West US 3
- **Quick startup** - Jobs start in seconds

## Prerequisites

1. **Azure CLI** logged in: `az login`
2. **ACR** with pipeline image: `../setup-acr.sh`
3. **.env file** with API keys

## Setup

```bash
# Set storage credentials
export STORAGE_ACCOUNT_NAME=vmstprod01
export STORAGE_SHARE_NAME=evaluation-db
export STORAGE_ACCOUNT_KEY=$(az storage account keys list \
    --account-name vmstprod01 -g Humanitarian \
    --query "[0].value" -o tsv)

# Create Container Apps environment
./setup-container-apps.sh
```

## Usage

```bash
# Run 5 parallel containers
./run-pipeline-job.sh --jobs 5 --data-source uneg --skip-download --recent-first

# Check job status
./check_jobs.sh

# Delete completed jobs
./delete_jobs.sh --yes
```

## Scripts

| Script | Description |
|--------|-------------|
| `setup-container-apps.sh` | Create Container Apps environment |
| `run-pipeline-job.sh` | Submit parallel pipeline jobs |
| `check_jobs.sh` | Check job status and logs |
| `delete_jobs.sh` | Delete completed jobs |

## Options

```bash
./run-pipeline-job.sh --jobs N [--workers M] [orchestrator options]

Container options:
  --jobs N          Number of parallel containers
  --workers M       Workers per container (default: 1)
  --skip-build      Use existing Docker image

Orchestrator options:
  --data-source     Data source name (required)
  --num-records     Max documents to process
  --skip-download   Skip download step
  --skip-scan       Skip scan step
  --skip-parse      Skip parse step
  --skip-summarize  Skip summarize step
  --skip-index      Skip index step
  --recent-first    Process recent documents first
```

## Cost Estimates

Container Apps Consumption tier:
- **vCPU:** $0.000024/second
- **Memory:** $0.000003/GiB-second
- **Free tier:** 180,000 vCPU-seconds/month

Example: 5 containers (4 vCPU, 8GB each) for 2 hours = ~$4.32

**Scale to zero = $0 when idle.**

## GPU Support

GPU workloads require West US 3 region:

```bash
# Create GPU environment
az containerapp env create \
    --name evidencelab-gpu-env \
    --resource-group Humanitarian \
    --location westus3 \
    --enable-workload-profiles

# Add GPU workload profile
az containerapp env workload-profile add \
    --name evidencelab-gpu-env \
    --resource-group Humanitarian \
    --workload-profile-name gpu-a100 \
    --workload-profile-type NC24-A100 \
    --min-nodes 0 \
    --max-nodes 1
```
