# Evidence Lab AI

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests/)

![Evidence Lab](ui/frontend/public/docs/images/evidence-lab.png)

## Introduction

Evidence Lab is a document pipeline, search, and AI-powered discovery stack built for humanitarian evaluation reports.

- Learn what the project is and why it exists: [`ui/frontend/public/docs/about.md`](ui/frontend/public/docs/about.md)
- Read the technical deep dive: [`ui/frontend/public/docs/tech.md`](ui/frontend/public/docs/tech.md)

## Getting started

You can explore the hosted version at [evidencelab.ai](https://evidencelab.ai).

### Quick Start

1. **Configure data sources**
   - Edit `config.json` in the repo root to define `datasources`, `data_subdir`, `field_mapping`, and `taxonomies`.
   - The UI reads the same `config.json` via Docker Compose.

2. **Set environment variables**
   - Copy `.env.example` to `.env`.
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
             report_124.error (if there was an error downloading the file)
   ```

4. **Run the pipeline (Docker)**
```bash
   # Start services
docker compose up -d --build

   # Run the orchestrator (example: UNEG)
   docker compose exec pipeline \
     python -m pipeline.orchestrator --data-source uneg --skip-download --num-records 10
   ```

5. **Access the Evidence Lab UI**
   - Open http://localhost:3000
   - Select your data source and search the indexed documents

6. **Next steps**
   - See the technical deep dive for pipeline commands, downloaders, and architecture details:
     [`ui/frontend/public/docs/tech.md`](ui/frontend/public/docs/tech.md)

## Documentation

- [`ui/frontend/public/docs/about.md`](ui/frontend/public/docs/about.md) - project background and goals
- [`ui/frontend/public/docs/tech.md`](ui/frontend/public/docs/tech.md) - architecture and pipeline details
- [`CONTRIBUTING.md`](CONTRIBUTING.md) - tests, evaluation, performance, and CI
