## Getting Started

For more detailed instructions refer to the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).

### Demo (quickest way to try it)

The interactive demo script guides you through provider selection, API key
setup, downloads a few World Bank documents, and runs the full pipeline.

**Running on host** (recommended — can use hardware acceleration such as Apple
MPS or NVIDIA CUDA, but may require some adjustments to suit your environment):

```bash
# Create and activate a virtual environment
python3 -m venv ~/.venvs/evidencelab-ai
source ~/.venvs/evidencelab-ai/bin/activate
pip install -r requirements.txt

# Start infrastructure services (Qdrant, PostgreSQL)
docker compose up -d qdrant postgres

# Run the demo — interactive setup will prompt for provider and API keys
python scripts/demo/run_demo.py --mode host
```

The script will automatically configure `.env`, add a demo datasource to
`config.json`, download documents, and run the pipeline.

**Running in Docker** (guaranteed to work on any Docker-capable machine, but
can be significantly slower as it cannot utilise GPU or Apple MPS acceleration
on your host):

```bash
# Start all services
docker compose up -d --build

# Run the demo
python scripts/demo/run_demo.py --mode docker
```

Once complete, open http://localhost:3000 and select the **demo** data source.

**Options:**

```bash
python scripts/demo/run_demo.py --mode host --num-docs 10   # Download more documents
python scripts/demo/run_demo.py --mode host --skip-download  # Re-run pipeline only
python scripts/demo/run_demo.py --mode host --skip-pipeline  # Download only
```

### Full Setup

1. **Configure data sources**
   - Edit [`config.json`](https://github.com/dividor/evidencelab/blob/main/config.json) in the repo root to define `datasources`, `data_subdir`, and `field_mapping`, along with fields to control how your documents are parsed.
   - The UI reads the same `config.json` via Docker Compose.

2. **Set environment variables**
   - Copy [`.env.example`](https://github.com/dividor/evidencelab/blob/main/.env.example) to `.env`.
   - Fill in the API keys and service URLs required by the pipeline and UI.

3. **Add documents + metadata**
   - Save documents under `data/<data_subdir>/pdfs/<organization>/<year>/`.
   - For each document, include a JSON metadata file with the same base name.
   - If a download failed, add a `.error` file with the same base name (scanner records these).

   Example layout:
   ```
   data/
     uneg/
       pdfs/
         UNDP/
           2024/
             report_123.pdf
             report_123.json
             report_124.error (optional, if download failed)
   ```

4. **Run the pipeline (Docker)**
   ```bash
   # Start services
   docker compose up -d --build

   # Run the orchestrator (example: UNEG)
   docker compose exec pipeline \
     python -m pipeline.orchestrator --data-source uneg --skip-download --num-records 10
   ```

   > **Tip:** Running the pipeline in Docker can be slow because it doesn't have access to GPU or Apple MPS acceleration. For faster processing using your host machine's hardware directly, use the host runner script instead:
   >
   > ```bash
   > ./scripts/pipeline/run_pipeline_host.sh --data-source uneg --num-records 10
   > ```
   >
   > See [Pipeline Configuration → Running on the Host](/docs/admin/pipeline-configuration.md) for full details.

5. **Access the Evidence Lab UI**
   - Open http://localhost:3000
   - Select your data source and search the indexed documents

For more detailed information see the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).
