# Azure Pipeline Scaling

Run the Evidence Lab pipeline on Azure for scalable document processing.

## Options

| Service | Best For | Cost Model | GPU Support |
|---------|----------|------------|-------------|
| **[Container Apps](./container-apps/)** | Quick jobs, auto-scaling | Pay-per-second | Yes (A100) |
| **[Batch](./batch/)** | Large batch jobs, cost optimization | Pay-per-second | Yes |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  VM (vm-prod-01) - Always On                                │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐                 │
│  │   UI    │  │   API   │  │   Qdrant    │──► Port 6333    │
│  └─────────┘  └────┬────┘  └──────┬──────┘   (API Key)     │
│                    │              │                         │
│              Internal Docker      │                         │
└───────────────────────────────────┼─────────────────────────┘
                                    │ HTTP + API Key
                      http://evidencelab.ai:6333
        ┌───────────────────────────┼─────────────────────────┐
        │     Azure Compute (Container Apps or Batch)         │
        │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
        │  │ Worker 1 │ │ Worker 2 │ │ Worker N │            │
        │  └──────────┘ └──────────┘ └──────────┘            │
        │         ▲                                           │
        │         └── Azure Files (shared storage)            │
        └─────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Azure CLI** installed and logged in:
   ```bash
   az login
   az account set --subscription "Your Subscription"
   ```

2. **Docker** installed for building images

3. **.env file** with required API keys:
   ```
   QDRANT_API_KEY=your-key
   HUGGINGFACE_API_KEY=your-key
   NOVITA_API_KEY=your-key  # Optional, for LLM
   ```

4. **Qdrant exposed** on port 6333 with API key authentication

## Quick Start

### 1. Create Azure Container Registry (shared)

```bash
./setup-acr.sh
```

### 2. Choose your compute option:

**Container Apps** (recommended for getting started):
```bash
cd container-apps/
./setup-container-apps.sh
./run-pipeline-job.sh --jobs 5 --data-source uneg --skip-download
```

**Batch** (for cost optimization):
```bash
cd batch/
./setup-batch.sh
./run-batch-job.sh --data-source uneg --skip-download
```

## Folder Structure

```
scripts/azure/
├── README.md              # This file
├── setup-acr.sh           # Create Azure Container Registry (shared)
├── container-apps/        # Container Apps scripts
│   ├── README.md
│   ├── setup-container-apps.sh
│   ├── run-pipeline-job.sh
│   ├── check_jobs.sh
│   └── delete_jobs.sh
└── batch/                 # Azure Batch scripts
    ├── README.md
    ├── setup-batch.sh
    ├── run-batch-job.sh
    └── check-batch-job.sh
```

## Cost Comparison

| Service | VM Size | vCPU | RAM | ~Cost/hour | Notes |
|---------|---------|------|-----|------------|-------|
| Container Apps | Consumption | 4 | 8GB | $0.35 | Auto-scale to 0 |
| Container Apps | GPU (A100) | 24 | 220GB | $3.67 | West US 3 only |
| Batch | D4s_v3 | 4 | 16GB | $0.19 | Manual scale |

**Note:** Both services support scaling to 0 = $0 when idle.

## Troubleshooting

### "Unauthorized" from Qdrant
- Check `QDRANT_API_KEY` in `.env`
- Test: `curl -H "api-key: YOUR_KEY" http://evidencelab.ai:6333/collections`

### Jobs can't connect to Qdrant
- Verify port 6333 is open in Azure NSG
- Check Qdrant is running: `docker ps | grep qdrant`

### Storage mount issues
- Verify Azure Files share exists
- Check storage credentials are correct

See individual README files in `container-apps/` and `batch/` for service-specific troubleshooting.
