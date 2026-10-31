## Getting Started

For more detailed instructions refer to the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).

### Demo (quickest way to try it)

Run Evidence Lab from the published Docker Hub image
([`astrobagel/evidencelab`](https://hub.docker.com/r/astrobagel/evidencelab)),
with nothing to build. You need Docker with Compose, Python 3 and git, plus an
API key for one model provider (Azure Foundry, Hugging Face or Google Vertex).

```bash
git clone https://github.com/dividor/evidencelab.git
cd evidencelab
python3 scripts/demo/run_demo.py --mode hub
```

The script asks which provider to use and for its key, then writes `.env`
(generating every password and secret), adds a demo data source to
`config.json`, downloads three World Bank reports, processes them inside the
published image and starts Evidence Lab. When it finishes, open
http://localhost:8080 and select the **Demo Data from World Bank** data source.
Add `--version 1.6.5` to run a specific release instead of `latest`. See
[Running from the Published Image](../admin/docker-images.md) for the details.

**Running on host instead** (faster parsing, because it can use hardware
acceleration such as Apple MPS or NVIDIA CUDA, but it needs the Python
dependencies and may require some adjustments to suit your environment):

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

**Running with the development Docker stack** (builds the images from source):

```bash
# Start all services
docker compose up -d --build

# Run the demo
python scripts/demo/run_demo.py --mode docker
```

With the host or development stack, open http://localhost:3000 and select the
**Demo Data from World Bank** data source.

**Options** (any mode):

```bash
python3 scripts/demo/run_demo.py --mode hub --num-docs 10    # Download more documents
python3 scripts/demo/run_demo.py --mode hub --skip-download  # Re-run pipeline only
python3 scripts/demo/run_demo.py --mode hub --skip-pipeline  # Download only
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
   > See [Pipeline Configuration → Running on the Host](../admin/pipeline-configuration.md) for full details.

5. **Access the Evidence Lab UI**
   - Open http://localhost:3000
   - Select your data source and search the indexed documents

For more detailed information see the [Evidence Lab GitHub Repo](https://github.com/dividor/evidencelab).
