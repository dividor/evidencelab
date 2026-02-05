# Unit Tests

Unit tests for the Evidence AI document processing pipeline.

## Overview

These tests verify individual components in isolation:
- Document scanning and metadata extraction
- JSON download and parsing
- Document parsing (PDF, DOCX, etc.)
- Text summarization
- Data source isolation
- Rate limiting
- UI highlighting functionality
- Statistics and metrics

## Running Tests

### All Unit Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Or using marker
pytest -m unit -v
```

### Specific Test Files

```bash
# Test document scanning
pytest tests/unit/test_scan.py -v

# Test parsing
pytest tests/unit/test_parse.py -v

# Test summarization
pytest tests/unit/test_summarize.py -v
```

### Run with Coverage

```bash
pytest tests/unit/ --cov=pipeline --cov-report=html
```

## Test Files

- `test_basic.py` - Basic functionality tests
- `test_data_source_isolation.py` - Data source separation tests
- `test_download_json.py` - JSON metadata download tests
- `test_highlight_consistency.py` - UI text highlighting tests
- `test_highlight_scroll.py` - UI scroll-to-highlight tests
- `test_parse.py` - Document parsing tests
- `test_rate_limit.py` - API rate limiting tests
- `test_scan.py` - Document scanning tests
- `test_scroll_stability.py` - UI scroll stability tests
- `test_scroll_to_highlight.py` - UI scroll navigation tests
- `test_stats.py` - Statistics calculation tests
- `test_summarize.py` - Document summarization tests
- `test_visual_metadata.py` - Visual metadata extraction tests

## Requirements

Unit tests generally don't require external services, but some tests may need:
- Mock data
- Temporary files
- Test fixtures

## Writing New Unit Tests

1. Create test file with `test_` prefix
2. Use descriptive test names: `test_<what>_<when>_<then>`
3. Use fixtures for shared setup
4. Mock external dependencies
5. Keep tests isolated and independent

Example:

```python
import pytest
from pipeline.processors.parsing.parser import ParseProcessor

def test_parser_extracts_title():
    """Test that parser correctly extracts document title."""
    processor = ParseProcessor()
    result = processor.parse("test.pdf")
    assert result["title"] is not None
```
