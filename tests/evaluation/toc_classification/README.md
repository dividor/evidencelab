# TOC Classification Evaluation Scripts

This directory contains scripts for evaluating and testing Table of Contents (TOC) classification and correction.

## Scripts

### `test_toc_hierarchy.py`
Judge TOCs stored in the database using LLM validation.

**Usage:**
```bash
# Process multiple documents
python tests/evaluation/toc_classification/test_toc_hierarchy.py --records 5

# Process a single document by file ID
python tests/evaluation/toc_classification/test_toc_hierarchy.py --file-id <file_id>

# Specify output file
python tests/evaluation/toc_classification/test_toc_hierarchy.py --records 5 --output my_results.xlsx
```

**Options:**
- `--records N`: Process N documents (mutually exclusive with `--file-id`)
- `--file-id ID`: Process a single document by file ID (mutually exclusive with `--records`)
- `--output PATH`: Output Excel file path (default: `toc_evaluation_results.xlsx`)

**Output:**
- Excel file with columns: `doc_id`, `title`, `eval_result`, `eval_reason`, `rendered_prompt`
- Evaluation uses the model specified by `EVAL_MODEL` constant (default: `qwen2.5-72b-instruct`)

### `predict_one_toc_all.py`
Test TOC classification on a single file. Reparses document and predicts section types.

**Usage:**
```bash
python tests/evaluation/toc_classification/predict_one_toc_all.py --file-id <file_id> [--reparse] [--data-source uneg]
```

**Options:**
- `--file-id ID`: The Qdrant Point ID of the file (required)
- `--reparse`: Reparse the document and use generated TOC for prediction
- `--data-source SOURCE`: Data source suffix (default: `uneg`)

### `predict_toc_tags.py`
Predict TOC tags from a CSV file.

**Usage:**
```bash
python tests/evaluation/toc_classification/predict_toc_tags.py <input_csv> <output_csv> [--limit N]
```

### `extract_tocs.py`
Extract TOCs from documents.

## Script Name Changes

The following scripts were renamed:
- `test_tocs_fix.py` → `test_toc_hierarchy.py`
- `test_one_toc.py` → `predict_one_toc_all.py`
