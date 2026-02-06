# Evidence Lab

[![CI](https://github.com/dividor/evidencelab/actions/workflows/ci.yml/badge.svg)](https://github.com/dividor/evidencelab/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Security: Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Security: Gitleaks](https://img.shields.io/badge/security-gitleaks-blue.svg)](https://github.com/gitleaks/gitleaks)
[![Container: Trivy](https://img.shields.io/badge/container-trivy-aqua.svg)](https://github.com/aquasecurity/trivy)

## Introduction

![Evidence Lab](ui/frontend/public/docs/images/evidence-lab.png)

Evidence lab is a free open source prototyping platform that provides a document pipeline, search, and AI-powered information discovery tools. The aim is to provide a quick start for those looking to use AI with their documents and a place where new ideas can be tested.

You can run the code yourself, or explore the online version at [evidencelab.ai](https://evidencelab.ai) which has so far been populated with 20,000 United Nations humanitarian evaluation reports sourced from the [United Nations Evaluation Group](https://www.un.org/evaluations) and 8,000 reports related to Fraud and Program Integrity as sourced from [The World Bank](https://www.worldbank.org/ext/en/home). See [Data](/data) for more information on these amazing documents.

If you would like to have your public documents added to Evidence Lab, or would like to contribute to the project, please reach out to [evidence-lab@astrobagel.com](mailto:evidence-lab@astrobagel.com).

Also, for the latest news check out the [AstroBagel Blog](https://medium.com/@astrobagel).

## Philosphy

Evidence lab was developed out of research work for the blog, so core principals are ...

* The full pipeline can run on a desktop computer and process 20,000 30-page documents in a week for less than $50.
* The pipeline and user interface should be easily configured for use with any folder of documents
* Should support quick/cheap parsing to start, with ability to activate more complex components later on without having to reprocess everything
* The platform can run with open as well as proprietary models
* The environment should have tools for easily monitoring processing as well as exploring AI information retrieval

Some lofty, often conflicting, goals! Always a work in progress, and low-cost high-speed processing which runs on a desktop computer, does come with a few shortcuts. To run on a modest server, the user interface might not be the fastest out there, and in not using expensive LLMs for parsing (only cheap ones!), the ingestion had to be tuned to the document data styles. That said, the design has tried to allow for future improvements.

## Features

Evidence lab document processing pipeline include the following features:

1. Processing pipeline

- PDF/Word parsing with Docling, to include document structure detection
- Footnote and references, images and table detection
- Basic table extraction, with support for more expensive processing as required
- AI-assisted document summarization
- AI-assisted tagging of documents
- Indexing with Open (Huggingface) or propriety models (Azure foundry, but extensible)

2. User interface

- Hybrid search with AI summary and reranking
- Filtering by metadata, in-document section types
- Search and reranking settings to explore different models
- Semanitic highlighting in search results
- Basic language translation 
- PDF preview with in-document search
- Administration views to track pipeline, documents, performance and errors
- Experimental features such as heatmapper to tracking trends in content

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
