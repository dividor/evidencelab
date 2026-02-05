# Integration Tests

End-to-end integration tests for the Evidence AI document processing pipeline.

## Overview

These tests verify the complete end-to-end system:
1. **Pipeline Processing**: Reindex a single test document
2. **API Functionality**: Search endpoints return correct data
3. **UI Rendering**: Playwright tests verify actual visual rendering in browser

**IMPORTANT**: These tests use the **`uneg` data source** and reindex a single test document (ID 4121 - Liberia evaluation report). They do not create a separate test data source.

## Test Data

- **Document**: Independent Country Programme Evaluation: Liberia - Main Report (UNDP 2025)
- **Location**: `tests/integration/data/`
- **Metadata**: `tests/integration/data/metadata.json`
- **Data Source**: `uneg` (main production data source)
- **Document ID**: 4121

## Prerequisites

The integration tests require:

1. **Document must be parsed**: The test document must already exist in `uneg` with status `parsed` or higher
2. **Services running**: Full application stack must be up

```bash
# Start all services
docker compose up -d

# Verify services are running
docker compose ps
```

Required services:
- **Qdrant**: Vector database (port 6333)
- **Pipeline**: Processing service + test runner
- **API**: FastAPI backend (container URL http://api:8000)
- **UI**: React frontend (container URL http://ui:3000)

## Running Tests

### **Run tests INSIDE the pipeline container**

```bash
# Run all integration tests (reindexes document)
docker compose exec -T pipeline /bin/bash -lc \
  "API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 python -m pytest tests/integration -v -s"

# Run specific test
docker compose exec -T pipeline /bin/bash -lc \
  "API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 python -m pytest tests/integration/test_pipeline_ui.py::TestPipelineIntegration::test_figure2_ui_rendering -v -s"

# Run only API tests (no UI/Playwright)
docker compose exec -T pipeline /bin/bash -lc \
  "API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 python -m pytest tests/integration -v -s -k 'not ui_rendering'"

# Run ONLY UI tests (skip reindexing - assumes document already indexed)
docker compose exec -T pipeline /bin/bash -lc \
  "SKIP_PIPELINE=1 API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 python -m pytest tests/integration -v -s -k 'ui_rendering'"
```

### Run the pipeline on the host (fast)

You can run the pipeline on the host (outside Docker) and then run the tests in Docker
with `SKIP_PIPELINE=1`. This is useful when host execution is faster.

1) Run the pipeline on the host for the test document:

```bash
RUN_PIPELINE_ON_HOST=1 INTEGRATION_FILE_ID=4121 ./scripts/pipeline/run_pipeline_host.sh
```

2) Run integration tests in Docker using the pre-indexed document:

```bash
docker compose exec -T pipeline /bin/bash -lc \
  "SKIP_PIPELINE=1 API_BASE_URL=http://api:8000 UI_BASE_URL=http://ui:3000 python -m pytest tests/integration -v -s"
```

### One-shot host pipeline + Docker tests

This script runs the host pipeline for the integration file, restarts containers,
waits for the API health check, and then runs integration tests in Docker with
`SKIP_PIPELINE=1`:

```bash
tests/integration/run_integration_host_pipeline.sh
```

### Why run in Docker?

1. **Playwright dependencies**: The tests use Playwright which requires Chromium browser binaries
2. **Network access**: Tests need to reach `http://api:8000` (API) and `http://ui:3000` (UI)
3. **Pipeline imports**: Tests import pipeline modules which are installed in the container

### Playwright Installation (if needed)

If you see errors about missing Playwright browsers:

```bash
# Install Playwright browsers in the container
docker compose exec pipeline python -m playwright install chromium
docker compose exec pipeline python -m playwright install-deps
```

## Test Cases

### 1. API Tests

#### `test_figure2_images_and_table`
- **Query**: "FIGURE 2. Expenditures by"
- **Verifies**: First result contains 2 images and 1 table (via `chunk_elements`)
- **Purpose**: Ensures inline images and tables are correctly included with captions

#### `test_table_only_chunk`
- **Query**: "Graph 2. UNDP Liberia"
- **Verifies**: First result is a pure table chunk (element_type="table")
- **Purpose**: Ensures chunks containing ONLY tables (no text elements) are correctly indexed

#### `test_footnotes_and_captions`
- **Query**: "FIGURE 2. Expenditures by"
- **Verifies**:
  - At least one element with `is_reference=True` (footnote with superscript number)
  - At least one element with `label="caption"` (figure/table caption)
- **Purpose**: Ensures footnotes and captions are properly detected and flagged

### 2. UI Tests (Playwright)

#### `test_figure2_ui_rendering`
- **Query**: "FIGURE 2. Expenditures by"
- **Verifies**:
  - References with superscript numbers are visible (`<sup>`)
  - Captions have special styling (centered, bold)
  - At least 2 images are rendered
  - Caption styling (centered, bold ≥600)
  - Reference styling (italic, left border)
- **Purpose**: End-to-end verification of visual rendering in actual browser

## Test Fixtures

### `test_document` (module-scoped)
Loads document metadata from `metadata.json`.

### `pipeline_processed` (module-scoped)
Reindexes the test document:
1. Verifies document exists and is parsed
2. Deletes existing chunks for the document
3. Resets status to 'parsed'
4. Runs orchestrator: `--skip-download --skip-scan --skip-parse --skip-summarize`
5. Verifies document reaches `status="indexed"`
6. Returns document ID, status, and chunk count

**Why module-scoped?**
- Indexing takes ~2 minutes
- All tests use same indexed document
- Reduces test time from 10min → 2min

## Environment Variables

- `SKIP_PIPELINE=1`: Skip reindexing, assume document already indexed
- `RUN_PIPELINE_ON_HOST=1`: Run pipeline on host (requires running tests on host)
- `INTEGRATION_FILE_ID`: File id passed to `run_pipeline_host.sh` (default test doc is 4121)
- `API_BASE_URL`: API endpoint (**required**: `http://api:8000`)
- `UI_BASE_URL`: UI endpoint (**required**: `http://ui:3000`)

## Troubleshooting

### Document not found

```
Document 4121 not found in uneg. Document must exist and be parsed first.
```

**Solution**: The test document must be downloaded and parsed before running tests:

```bash
docker compose exec pipeline python -m pipeline.orchestrator --data-source uneg --num-records 1
```

### Playwright errors

```
ModuleNotFoundError: No module named 'playwright'
```

**Solution**: Install Playwright in the container:

```bash
docker compose exec pipeline pip install playwright
docker compose exec pipeline python -m playwright install chromium
```

### UI not loading

Make sure the UI container is running:

```bash
docker compose ps ui
docker compose logs ui
```

## Adding New Tests

1. Add test method to `TestPipelineIntegration` class
2. Use `pipeline_processed` fixture to ensure document is indexed
3. For API tests: use `requests` to call `{API_BASE_URL}/search`
4. For UI tests: use Playwright's `sync_playwright()` context manager
5. Run tests to verify: `docker compose exec pipeline pytest tests/integration/ -v -s`
