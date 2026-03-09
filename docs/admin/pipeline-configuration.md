## Pipeline Configuration

Evidence Lab's document processing pipeline is driven by a single configuration file — `config.json` in the repository root. This file controls everything from which AI models are used for embeddings and summarization, to how your source metadata fields map to Evidence Lab's internal schema.

---

### Config File Structure

The `config.json` file has six top-level sections:

| Section | Purpose |
|---------|---------|
| `application` | Global application settings (search tuning, feature toggles) |
| `supported_embedding_models` | Registry of available embedding models |
| `supported_llms` | Registry of available LLM models |
| `supported_rerank_models` | Registry of available reranking models |
| `ui_model_combos` | Named presets that bundle models together for the UI |
| `datasources` | Per-datasource configuration (field mappings, pipeline stages, filters) |

---

### Application Settings

The `application` section controls global behavior:

```json
{
  "application": {
    "ai_summary": { "enabled": true },
    "features": {
      "semantic_highlights": true,
      "pdf_highlights": true
    },
    "search": {
      "dense_weight": 0.5,
      "short_query_dense_weight": 0.25,
      "highlight_threshold": 0.6,
      "page_size": 50,
      "default_dense_model": "e5_large"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ai_summary.enabled` | boolean | Enable or disable AI-generated summaries in search results |
| `features.semantic_highlights` | boolean | Highlight semantically relevant phrases in search results |
| `features.pdf_highlights` | boolean | Show bounding-box highlights in the PDF viewer |
| `search.dense_weight` | float (0–1) | Balance between semantic (1.0) and keyword (0.0) search. Default: 0.5 |
| `search.short_query_dense_weight` | float | Override dense weight for very short queries (1–2 words) |
| `search.highlight_threshold` | float | Minimum similarity score for a phrase to be highlighted |
| `search.page_size` | int | Default number of results per page |
| `search.default_dense_model` | string | Fallback embedding model name if no datasource specifies one |

---

### Model Registries

Evidence Lab maintains three model registries. Each entry uses a short nickname as its key.

#### Embedding Models (`supported_embedding_models`)

Each entry defines a model that can be used for vector embeddings:

| Field | Type | Description |
|-------|------|-------------|
| `model_id` | string | Full model identifier (e.g., `"intfloat/multilingual-e5-large"`) |
| `size` | int | Vector dimensionality (e.g., 1024) |
| `source` | string | Provider: `"huggingface"`, `"azure_foundry"`, `"google_vertex"`, `"fastembed"` |
| `type` | string | `"dense"` or `"sparse"` |
| `max_tokens` | int | Maximum input token length |

The `source` field determines how the model is loaded:
- **`huggingface`** / **`fastembed`** — runs locally via an embedding server (requires GPU or MPS for best performance)
- **`azure_foundry`** / **`google_vertex`** — accessed via remote API (requires API keys in `.env`)

#### LLM Models (`supported_llms`)

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Full model identifier (e.g., `"gpt-4.1-mini"`, `"gemini-2.5-flash"`) |
| `provider` | string | `"huggingface"`, `"azure_foundry"`, or `"google_vertex"` |
| `inference_provider` | string | Optional routing provider (e.g., `"together"`, `"novita"`) |
| `max_tokens` | int | Maximum output tokens |

#### Rerank Models (`supported_rerank_models`)

| Field | Type | Description |
|-------|------|-------------|
| `model_id` | string | Model identifier |
| `source` or `provider` | string | `"huggingface"` for local, `"azure_foundry"` / `"google_vertex"` for API |

---

### UI Model Combos

Model combos are named presets that bundle embedding, LLM, and reranking models together. Users select these from the **Models** dropdown in the top bar.

```json
{
  "ui_model_combos": {
    "Azure Foundry": {
      "embedding_model": "azure_small",
      "sparse_model": "bm25",
      "summarization_model": {
        "model": "gpt-4.1-mini",
        "max_tokens": 4096,
        "temperature": 0.1
      },
      "semantic_highlighting_model": {
        "model": "gpt-4.1-mini",
        "max_tokens": 4096,
        "temperature": 0.0
      },
      "reranker_model": "azure_rerank"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `embedding_model` | string | Key from `supported_embedding_models` for dense search |
| `sparse_model` | string | Sparse model name (typically `"bm25"`) |
| `summarization_model` | object | LLM settings for AI summaries (model, max_tokens, temperature) |
| `semantic_highlighting_model` | object | LLM settings for semantic phrase highlighting |
| `reranker_model` | string | Key from `supported_rerank_models` |

> **Validation:** At startup, Evidence Lab validates that every model reference in your combos exists in the corresponding registry. Invalid references prevent the application from starting.

---

### Datasource Configuration

Each datasource is a named entry under `datasources`. The key is a human-readable name (e.g., `"UN Humanitarian Evaluation Reports"`), and the value contains all configuration for that data source.

#### Top-Level Datasource Fields

| Field | Type | Description |
|-------|------|-------------|
| `data_subdir` | string | Directory name under `data/` (e.g., `"uneg"`). Also used as the internal identifier for collections. |
| `field_mapping` | object | Maps your metadata fields to Evidence Lab's internal fields |
| `example_queries` | string[] | Suggested queries shown on the homepage |
| `default_filter_fields` | object | Filters shown in the search sidebar (field name → display label) |
| `metadata_panel_fields` | object | Fields shown in the document metadata panel |
| `pipeline` | object | Processing pipeline configuration (see below) |

#### Field Mapping

The `field_mapping` object is how you tell Evidence Lab which fields in your source metadata correspond to its internal schema. The left side is Evidence Lab's field name, the right side is your metadata's field name.

```json
{
  "field_mapping": {
    "title": "display_title",
    "organization": "agency",
    "published_year": "YEAR(docdt)",
    "country": "country_name",
    "document_type": "fixed_value:Evaluation Report",
    "pdf_url": "pdf_url",
    "report_url": "report_url"
  }
}
```

**Core fields you can map:**

| Evidence Lab Field | Description |
|-------------------|-------------|
| `title` | Document title |
| `organization` | Publishing organization |
| `published_year` | Year of publication |
| `document_type` | Type of document |
| `country` | Country or countries covered |
| `region` | Geographic region |
| `language` | Document language |
| `abstract` | Document abstract or description |
| `pdf_url` | URL to the PDF file |
| `report_url` | URL to the report landing page |

**Three types of mapping values:**

1. **Direct field reference** — `"title": "display_title"` maps directly to the `display_title` field in your metadata JSON.

2. **Fixed value** — `"organization": "fixed_value:World Bank"` sets the field to a constant value for every document. Useful when all documents in a datasource come from the same organization.

3. **Transform function** — `"published_year": "YEAR(docdt)"` applies a function to extract a value from a source field.

#### The YEAR() Macro

The `YEAR()` macro extracts a four-digit year from an ISO 8601 date string. This is useful when your metadata stores full dates but Evidence Lab needs just the year.

**Syntax:** `YEAR(field_name)`

**Example:** If your metadata contains `"docdt": "2023-06-15T00:00:00Z"`, the mapping `"published_year": "YEAR(docdt)"` produces `"2023"`.

The macro handles various date formats including ISO 8601 with timezone indicators. If the date cannot be parsed, the field is set to `null` and a warning is logged.

#### Multi-Value Fields

Fields like `country`, `region`, and `theme` support multiple values. If the source metadata contains semicolon-separated values (e.g., `"Kenya; Tanzania; Uganda"`), Evidence Lab automatically splits them into a list. Scalar fields like `title`, `published_year`, and `organization` are always stored as single values.

---

### Pipeline Stages

The `pipeline` object within each datasource configures each processing stage:

#### Download

```json
{
  "pipeline": {
    "download": {
      "command": "pipeline/integration/my-integration/download.py",
      "args": ["--data-dir", "{data_dir}", "--num-records", "{num_records}"]
    }
  }
}
```

The `args` array supports placeholders that are resolved from orchestrator CLI arguments:

| Placeholder | CLI Argument | Description |
|-------------|-------------|-------------|
| `{data_dir}` | (automatic) | Target download directory |
| `{num_records}` | `--max-results` | Maximum documents to download |
| `{year}` | `--year` | Filter by specific year |
| `{from_year}` | `--from-year` | Start of year range |
| `{to_year}` | `--to-year` | End of year range |
| `{agency}` | `--agency` | Filter by organization |

When a placeholder resolves to `null`, both it and its preceding flag are cleanly omitted from the command line.

#### Parse

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `table_mode` | string | `"fast"` | Docling table extraction: `"fast"` or `"accurate"` |
| `no_ocr` | boolean | `true` | Disable OCR for faster processing |
| `images_scale` | float | `1.0` | Image resolution scale factor |
| `enable_superscripts` | boolean | `true` | Enable superscript/footnote detection |
| `use_subprocess` | boolean | `false` | Run parsing in a subprocess for OOM protection |
| `subprocess_timeout` | int | `1200` | Timeout in seconds for subprocess parsing (20 minutes) |

#### Chunk

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `max_tokens` | int | **Yes** | Maximum token count per chunk |
| `min_substantive_size` | int | No (default: 100) | Minimum character count to keep a chunk |
| `tokenizer` | string | **Yes** | Tokenizer model ID for counting tokens |

#### Summarize

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable document summarization |
| `dense_model` | string | Required | Embedding model for extractive summarization |
| `llm_model` | object | Required | LLM configuration (model, temperature, max_tokens) |
| `llm_workers` | int | `1` | Concurrent LLM inference workers |
| `context_window` | int | `29000` | Max characters for LLM context (larger documents use map-reduce) |

#### Tag

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable document tagging |
| `dense_model` | string | Required | Embedding model for semantic tagging |
| `llm_model` | object | — | LLM configuration for taxonomy classification |
| `taxonomies` | object | — | Taxonomy definitions (see below) |

#### Index

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `batch_size` | int | `10` | Chunks to embed and upsert per batch |
| `embedding_workers` | int | `4` | Concurrent embedding threads |
| `dense_models` | string[] | `[]` | Embedding models to generate vectors for |
| `sparse_models` | string[] | `["bm25"]` | Sparse models for keyword search |
| `oversize_chunks_strategy` | string | `"truncate"` | Handle oversized chunks: `"truncate"` or `"stop"` |

> **Important:** The `dense_models` list determines which embedding vectors are stored in Qdrant. Only UI model combos whose `embedding_model` appears in this list will be available in the UI.

---

### Taxonomies

Taxonomies let you classify documents into categories using AI. Each taxonomy defines a set of values with LLM prompts that guide the classification.

```json
{
  "taxonomies": {
    "sdg": {
      "name": "United Nations Sustainable Development Goals",
      "level": "document",
      "input": "summary",
      "type": "multi",
      "values": {
        "sdg1": {
          "name": "SDG1 - No Poverty",
          "definition": "End poverty in all its forms everywhere",
          "llm_prompt": "Assign this tag if the document discusses..."
        }
      }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name for the taxonomy |
| `level` | string | Classification scope: `"document"` |
| `input` | string | Input to the LLM: `"summary"` (uses the document summary) |
| `type` | string | `"multi"` allows multiple values per document |
| `values` | object | Dictionary of taxonomy values, each with `name`, `definition`, and `llm_prompt` |

Taxonomy results are stored as `tag_{taxonomy_key}` fields (e.g., `tag_sdg`) and automatically appear as filter facets in the search sidebar.

Each taxonomy requires corresponding Jinja2 prompt templates in the `prompts/` directory: `taxonomy_{key}_system.j2` and `taxonomy_{key}_user.j2`.

---

### Running the Pipeline

```bash
# Process documents from a specific data source
docker compose exec pipeline \
  python -m pipeline.orchestrator --data-source uneg --skip-download --num-records 10

# Download and process
docker compose exec pipeline \
  python -m pipeline.orchestrator --data-source uneg --num-records 50

# Process a specific year range
docker compose exec pipeline \
  python -m pipeline.orchestrator --data-source uneg --from-year 2020 --to-year 2024

# Reprocess a single document
docker compose exec pipeline \
  python -m pipeline.orchestrator --data-source uneg --file-id doc_123
```

| Flag | Description |
|------|-------------|
| `--data-source` | Datasource `data_subdir` to process |
| `--skip-download` | Skip the download stage (process existing files only) |
| `--num-records` | Limit number of documents to process |
| `--year` | Process documents from a specific year |
| `--from-year` / `--to-year` | Process a year range |
| `--agency` | Filter by organization |
| `--file` | Process a specific file path |
| `--file-id` | Process a specific document by ID |

---

### Validation

Evidence Lab validates your configuration at startup:

- **Model references** — every model referenced in `ui_model_combos` and `pipeline` sections must exist in the corresponding registry
- **Required fields** — `chunk.max_tokens`, `chunk.tokenizer`, `summarize.llm_model.model`, and `tag.dense_model` are validated in processor constructors
- **Taxonomy templates** — each configured taxonomy must have matching Jinja2 prompt templates in the `prompts/` directory

Invalid configuration raises a `ValueError` and prevents the application from starting, so you'll catch errors early rather than encountering them mid-pipeline.
