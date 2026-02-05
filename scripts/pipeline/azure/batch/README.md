# Azure Batch Pipeline

Run the Evidence Lab pipeline on Azure Batch for cost-effective batch processing.

## Overview

Azure Batch provides:
- **Pay-per-second** VM billing (only when nodes are running)
- **Parallel processing** with multiple nodes and tasks
- **Azure Files mounting** for shared data access
- **Container support** for Docker workloads

## Prerequisites

1. **Azure CLI** logged in: `az login`
2. **ACR** with pipeline image: `../setup-acr.sh`
3. **Batch quota** - Request via Azure Portal:
   - Batch Account → Quotas → Request increase
   - DSv3 Series: 20+ vCPUs (for 5 nodes)
   - Pools: 1+

## Setup

```bash
# Set storage account (check existing with: az storage account list -g Humanitarian -o table)
export STORAGE_ACCOUNT_NAME="vmstprod01"
export FILES_SHARE_NAME="evaluation-db"

# Create Batch account and pool
./setup-batch.sh
```

## Usage

### Basic Usage

```bash
# Single task on 1 node
./run-batch-job.sh --data-source uneg --skip-download --skip-scan

# Check status
./check-batch-job.sh [job-id]

# Scale down when done (stops billing)
az batch pool resize --pool-id pipeline-pool --target-dedicated-nodes 0
```

### Parallel Processing

**Understanding the options:**

| Term | What it is |
|------|------------|
| **Node** | 1 VM (Standard_D4s_v3: 4 vCPUs, 16GB RAM, ~$0.19/hr) |
| **Job** | Number of partitions. Documents are split into N parts. |
| **Worker** | Parallel threads WITHIN each task for document processing |

**Total parallelism = nodes × workers** (since 1 task runs per node at a time)

```bash
# RECOMMENDED: 10 VMs, 10 partitions, 2 workers each = 20 docs processing at once
# Cost: ~$23 for 12 hours
./run-batch-job.sh --jobs 10 --nodes 10 --workers 2 \
  --data-source uneg --skip-download --recent-first

# BUDGET: 5 VMs (tasks queue), 2 workers each = 10 docs at once
# Cost: ~$11.50 for 12 hours
./run-batch-job.sh --jobs 10 --nodes 5 --workers 2 \
  --data-source uneg --skip-download --recent-first
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--nodes N` | Number of VMs to run | 1 |
| `--jobs N` | Number of partitions (set ≥ nodes) | 1 |
| `--workers W` | Parallel workers per task | 1 |

**Orchestrator options** (passed through):

| Option | Description |
|--------|-------------|
| `--data-source` | Data source name (required, e.g., 'uneg') |
| `--num-records` | Maximum documents to process per partition |
| `--skip-download` | Skip download step |
| `--skip-scan` | Skip scan step |
| `--skip-parse` | Skip parse step |
| `--skip-summarize` | Skip summarize step |
| `--skip-index` | Skip index step |
| `--recent-first` | Process recent documents first (applied before partitioning) |

### How Partitioning Works

When you specify `--jobs 10`, documents are split into 10 partitions:
- Task 1 processes partition 1/10 (first 10%)
- Task 2 processes partition 2/10 (next 10%)
- ...and so on

With `--recent-first`, documents are sorted by year (newest first) **before** partitioning:
- Partition 1/10 gets the most recent ~10% of documents
- Partition 10/10 gets the oldest ~10%

Each partition is independent with no overlap.

## Cost Estimation

| Nodes | vCPUs | RAM | Hourly Cost | Daily Cost (24h) |
|-------|-------|-----|-------------|------------------|
| 1 | 4 | 16GB | $0.19 | $4.61 |
| 5 | 20 | 80GB | $0.96 | $23.04 |
| 10 | 40 | 160GB | $1.92 | $46.08 |

**Important:** Scale to 0 when done to stop billing:
```bash
az batch pool resize --pool-id pipeline-pool --target-dedicated-nodes 0
```

## Scripts

| Script | Description |
|--------|-------------|
| `setup-batch.sh` | Create Batch account and pool |
| `run-batch-job.sh` | Submit pipeline job(s) |
| `check-batch-job.sh` | Check job status and costs |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Batch                          │
│  ┌──────────────┐    ┌──────────────────────────────┐  │
│  │ Batch Account│───▶│  Pool (D4s_v3 nodes)         │  │
│  └──────────────┘    │                              │  │
│                      │  ┌──────┐ ┌──────┐ ┌──────┐  │  │
│                      │  │Node 1│ │Node 2│ │Node N│  │  │
│                      │  │Task 1│ │Task 3│ │Task N│  │  │
│                      │  │Task 2│ │Task 4│ │      │  │  │
│                      │  └──────┘ └──────┘ └──────┘  │  │
│                      └──────────────┬───────────────┘  │
└─────────────────────────────────────┼──────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
             ┌───────────┐     ┌───────────┐     ┌───────────┐
             │Azure Files│     │  Qdrant   │     │    ACR    │
             │  (data)   │     │ (vectors) │     │  (images) │
             └───────────┘     └───────────┘     └───────────┘
```

## Troubleshooting

### "Quota exceeded" error
Request quota increase in Azure Portal → Batch Account → Quotas

### Pool creation fails
- Check VM size is available in your region
- Verify storage account exists and is accessible

### Task fails immediately
- Check container image exists in ACR: `az acr repository show-tags --name evidencelabacr --repository pipeline`
- Verify Azure Files mount configuration

### Tasks stuck in "active" state
- Check node count matches or exceeds task count
- Scale up more nodes: `az batch pool resize --pool-id pipeline-pool --target-dedicated-nodes N`
