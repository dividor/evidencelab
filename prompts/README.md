# LLM Prompts

This directory contains Jinja2 templates for LLM prompts used throughout the pipeline.

## Template Files

### TOC Classification Prompts

#### `toc_classification_system.j2`
System prompt for the TOC (Table of Contents) classification task.

**Purpose**: Defines the classification categories and rules for the LLM to follow when categorizing document sections.

**Variables**: None (static prompt)

**Categories**:
- `front_matter`: Acknowledgements, contents, foreword, team lists, cover pages
- `executive_summary`: Executive summary, evaluation brief, key findings overview
- `acronyms`: Acronyms, abbreviations, glossary
- `body`: Everything else (intro, methodology, findings, conclusions, chapters)
- `annexes`: Annex, appendix, references, TOR
- `appendices`: Appendices (plural form)
- `bibliography`: Bibliography, references list

#### `toc_classification_user.j2`
User prompt for the TOC classification task.

**Purpose**: Provides the document-specific information (title and TOC content) to the LLM.

**Variables**:
- `doc_title` (string): The title of the document being classified
- `toc_text` (string): The table of contents text with hierarchical heading levels

---

### Document Summarization Prompts

#### `summary_reduction.j2`
Prompt for reducing/summarizing document chunks or full documents.

**Purpose**: Instructs the LLM to generate a structured summary identifying key concepts, methods, findings, and terminology. Used in both single-pass summarization and the MAP phase of map-reduce.

**Variables**:
- `document_text` (string): The text content to summarize (full document or chunk)

**Output Format**:
- Summary (2-3 paragraphs)
- Main Topics
- Key Terms & Concepts
- Methods / Approach
- Findings / Conclusions
- Related Concepts / Themes

#### `summary_final.j2`
Prompt for the REDUCE phase of map-reduce summarization.

**Purpose**: Consolidates multiple chunk summaries into a comprehensive overview, identifying overarching themes and patterns.

**Variables**:
- `map_summaries` (string): Combined summaries from all document chunks

**Output Format**:
- Title
- Summary (2-3 paragraphs)
- Topics (thematic clusters)
- Core Concepts and Terms
- Methodological Patterns
- Key Conclusions

---

### Search AI Summary Prompts

#### `ai_summary_system.j2`
System prompt for search results summarization.

**Purpose**: Defines the assistant's role and output format when generating AI summaries of search results.

**Variables**: None (static prompt)

**Key Instructions**:
- Answer questions about humanitarian evaluations
- Provide 5-10 sentence paragraph answers
- Avoid conversational formatting
- Single paragraph output

#### `ai_summary_user.j2`
User prompt for search results summarization.

**Purpose**: Formats the user's query and top search results for the LLM to generate a relevant summary.

**Variables**:
- `query` (string): The user's search query
- `results` (list): List of search result dictionaries with fields like `title`, `organization`, `year`, `text`

**Output**: Presents the top 5 results with full text and asks for a comprehensive answer to the query.

---

## Usage

Templates are loaded using Jinja2's `Environment` and `FileSystemLoader`:

```python
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

prompts_dir = Path(__file__).parent.parent.parent / "prompts"
jinja_env = Environment(loader=FileSystemLoader(str(prompts_dir)))

# TOC Classification
system_template = jinja_env.get_template("toc_classification_system.j2")
user_template = jinja_env.get_template("toc_classification_user.j2")

system_prompt = system_template.render()
user_prompt = user_template.render(
    doc_title="Example Document",
    toc_text="[H2] Introduction | page 1\n[H3] Background | page 2"
)

# Document Summarization
reduction_template = jinja_env.get_template("summary_reduction.j2")
final_template = jinja_env.get_template("summary_final.j2")

reduction_prompt = reduction_template.render(
    document_text="Full document text here..."
)

final_prompt = final_template.render(
    map_summaries="Combined summaries from chunks..."
)

# Search AI Summary
ai_system_template = jinja_env.get_template("ai_summary_system.j2")
ai_user_template = jinja_env.get_template("ai_summary_user.j2")

ai_system_prompt = ai_system_template.render()
ai_user_prompt = ai_user_template.render(
    query="What are the key challenges in humanitarian evaluations?",
    results=[
        {
            "title": "Evaluation Report 2024",
            "organization": "UNHCR",
            "year": 2024,
            "text": "Full text of the result..."
        },
        # ... more results
    ]
)
```

## Adding New Templates

1. Create a new `.j2` file in this directory
2. Use Jinja2 syntax for variables: `{{ variable_name }}`
3. Document the template purpose and variables in this README
4. Load and render the template in your processor code
5. Enable prompt logging by setting the logger to INFO level

## Prompt Logging

### TOC Classification
When processing documents, the rendered TOC classification prompts are logged at INFO level with clear delimiters:

```
================================================================================
LLM TOC Classification Request
================================================================================
SYSTEM PROMPT:
<rendered system prompt>
--------------------------------------------------------------------------------
USER PROMPT:
<rendered user prompt>
================================================================================
LLM RESPONSE:
<model response>
================================================================================
```

### Document Summarization
Summary prompts are also logged with clear delimiters:

**Single-pass summarization:**
```
================================================================================
LLM Summary Request (Single-pass)
================================================================================
PROMPT:
<rendered reduction prompt>
================================================================================
LLM RESPONSE:
<summary>
================================================================================
```

**Map-reduce summarization:**
```
================================================================================
LLM Summary Request (Map-Reduce, Chunk 1/5)
================================================================================
CHUNK REDUCTION PROMPT:
<rendered reduction prompt for first chunk>
================================================================================

... (only first chunk logged to avoid spam) ...

================================================================================
LLM Summary Request (Final Reduction)
================================================================================
FINAL REDUCTION PROMPT:
<rendered final prompt with all chunk summaries>
================================================================================
LLM RESPONSE:
<final summary>
================================================================================
```

### Search AI Summary
AI summary prompts (from search results) are logged similarly:

```
================================================================================
AI Summary Request
================================================================================
SYSTEM PROMPT:
<rendered system prompt>
--------------------------------------------------------------------------------
USER PROMPT:
<rendered user prompt with search results>
================================================================================
AI SUMMARY RESPONSE:
<generated summary>
================================================================================
```

This makes it easy to debug classification and summarization issues and improve prompt quality.

## Where to Find Logs

- **Pipeline orchestrator** (summarization, TOC classification): `docker compose logs pipeline | grep "LLM"`
- **API service** (TOC reprocessing via UI, AI search summaries): `docker compose logs api | grep "LLM"`
- **Real-time monitoring**: `docker compose logs -f pipeline` or `docker compose logs -f api`

## Grep Patterns for Log Analysis

```bash
# See all LLM requests
docker compose logs api 2>&1 | grep -A 30 "LLM.*Request"
docker compose logs pipeline 2>&1 | grep -A 30 "LLM.*Request"

# See TOC classification prompts
docker compose logs api 2>&1 | grep -A 50 "TOC Classification"

# See document summary prompts
docker compose logs pipeline 2>&1 | grep -A 50 "Summary Request"

# See AI search summary prompts
docker compose logs api 2>&1 | grep -A 50 "AI Summary Request"

# See just system prompts
docker compose logs api 2>&1 | grep -A 20 "SYSTEM PROMPT:"

# See LLM responses
docker compose logs api 2>&1 | grep -A 30 "LLM RESPONSE:"
docker compose logs api 2>&1 | grep -A 30 "AI SUMMARY RESPONSE:"
docker compose logs pipeline 2>&1 | grep -A 30 "LLM RESPONSE:"
```
