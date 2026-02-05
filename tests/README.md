# Test Suite Refactoring

## Overview

Refactored the test suite into **unit** and **integration** tests with clear separation of concerns.

## Structure

```
tests/
├── unit/                          # Unit tests (isolated component testing)
│   ├── conftest.py
│   ├── README.md
│   ├── test_basic.py
│   ├── test_data_source_isolation.py
│   ├── test_download_json.py
│   ├── test_highlight_consistency.py
│   ├── test_highlight_scroll.py
│   ├── test_parse.py
│   ├── test_rate_limit.py
│   ├── test_scan.py
│   ├── test_scroll_stability.py
│   ├── test_scroll_to_highlight.py
│   ├── test_stats.py
│   ├── test_summarize.py
│   └── test_visual_metadata.py
│
└── integration/                   # Integration tests (end-to-end pipeline)
    ├── conftest.py
    ├── README.md
    ├── test_pipeline_ui.py
    └── data/                      # Test data
        ├── metadata.json
        └── independent_country_programme_evaluation_liberia_-_main_report_4121.pdf
```

Note: UI unit tests live under `ui/frontend/src/tests` and are run separately
from the Python test suites.

## Integration Tests

### Test Document
- **Title**: Independent Country Programme Evaluation: Liberia - Main Report
- **Agency**: UNDP
- **Year**: 2025
- **Size**: 2.1 MB, 66 pages
- **Location**: `tests/integration/data/`

### Test Cases (Current)

API-level coverage:
- `test_toc_hierarchy_and_labels`: TOC and classification fields are populated.
- `test_figure2_images_and_table`: FIGURE 2 search returns image elements.
- `test_table_only_chunk`: Graph 2 search returns a table element.
- `test_footnotes_and_captions`: footnote markers and captions persist.
- `test_search_health_keyword_boost`: short query returns keyword results.
- `test_caret_superscript_persistence`: caret superscripts preserved in output.
- `test_caret_footnote_definition_persistence`: footnote definitions preserved.

UI rendering coverage (Playwright):
- `test_figure2_ui_rendering`: captions and references render in UI.
- `test_graph2_table_ui_rendering`: table elements render in UI.
- `test_inline_reference_ui_rendering`: inline references render in UI.
- `test_image_placement_above_text`: images appear after caption text.
- `test_semantic_highlighting_in_search_results`: highlights appear in UI.
- `test_semantic_highlighting_precision`: highlight content matches expected phrases.

### Running Integration Tests

```bash
# Run all integration tests (Docker only)
docker compose exec -T -e API_BASE_URL=http://api:8000 -e UI_BASE_URL=http://ui:3000 \
  pipeline pytest tests/integration -v -s

# Run specific test
docker compose exec -T -e API_BASE_URL=http://api:8000 -e UI_BASE_URL=http://ui:3000 \
  pipeline pytest tests/integration/test_pipeline_ui.py::TestPipelineIntegration::test_figure2_ui_rendering -v -s

# Run with detailed output
docker compose exec -T -e API_BASE_URL=http://api:8000 -e UI_BASE_URL=http://ui:3000 \
  pipeline pytest tests/integration -v -s --tb=long

# Skip re-running the pipeline (requires document already indexed)
docker compose exec -T -e API_BASE_URL=http://api:8000 -e UI_BASE_URL=http://ui:3000 -e SKIP_PIPELINE=1 \
  pipeline pytest tests/integration/test_pipeline_ui.py -v -s
```

### Prerequisites

1. **Start Docker services**:
   ```bash
   docker compose up -d
   ```

2. **Verify services**:
   - Qdrant: http://localhost:6333
   - API (from container): http://api:8000
   - UI (from container): http://ui:3000
   - Pipeline: `docker compose ps pipeline`

3. **Install test dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Running All Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# Frontend unit tests (React)
docker compose exec -e CI=true ui npm test -- --watchAll=false

# Integration tests only (Docker)
docker compose exec -T -e API_BASE_URL=http://api:8000 -e UI_BASE_URL=http://ui:3000 \
  pipeline pytest tests/integration/ -v -s

# All tests
pytest -v

# With coverage
pytest --cov=pipeline --cov-report=html
```

## CI/CD Integration

The pytest.ini configuration supports test markers:

```ini
[pytest]
markers =
    unit: Unit tests
    integration: Integration tests (require full stack)
```

Usage in CI:
```bash
# Fast CI (unit only)
pytest -m unit

# Full CI (all tests)
pytest -m "unit or integration"
```

## Frontend Tests (React)

Frontend unit tests live in `ui/frontend/src/tests` and run with `react-scripts`.

```bash
docker compose exec -e CI=true ui npm test -- --watchAll=false
```

## Visual Regression Coverage

Integration tests include UI rendering checks (Playwright) that act as lightweight
visual regression coverage for key views (search result cards, captions, tables,
and image placement). They are not pixel-diff tests but validate DOM output and
rendering behavior end-to-end.

## Test Fixtures

### Unit Tests
- Minimal fixtures
- Mock external dependencies
- Fast execution

### Integration Tests
- `test_document`: Loads test metadata
- `pipeline_processed`: Runs full pipeline once unless `SKIP_PIPELINE=1`
- Cleanup automatic before each test run

## Key Changes

1. **Separation**: Unit tests isolated from integration tests
2. **Real Data**: Integration tests use actual document (Liberia evaluation)
3. **End-to-End**: Tests verify complete pipeline + search functionality
4. **Conditional Logic**: Tests confirm figure/table/diagram tolerance behavior
5. **Documentation**: README files in each test directory

## Future Enhancements

- [ ] Add screenshot diffing for visual regressions
- [ ] Expand Playwright coverage to more UI flows
- [ ] Add performance benchmarks
- [ ] Add more test documents with different characteristics
- [ ] Add visual regression tests
- [ ] Add load testing for API endpoints
