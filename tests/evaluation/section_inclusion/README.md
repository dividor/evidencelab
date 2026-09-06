# Section Inclusion Evaluation

Verifies that main-body content is not accidentally excluded from default Search
results because of how its sections are tagged.

## Why

Search has a **content type** filter (Search / Content settings). By default it
only returns chunks whose `tag_section_type` is one of the "real content" types:

```
executive_summary, context, methodology, findings, conclusions, recommendations, other
```

This list mirrors `DEFAULT_SECTION_TYPES` in
[`ui/frontend/src/utils/searchUrl.ts`](../../../ui/frontend/src/utils/searchUrl.ts).
Every other section type — `front_matter`, `acronyms`, `annexes`, `appendix`,
`bibliography`, `introduction`, … — is **excluded by default**.

Section tagging is automatic (done at upload by the TOC classifier). If a section
that is really part of the body gets mis-tagged as, e.g., `annexes`, that content
silently disappears from default search results.

Each document carries a **human-set** page range in its source metadata:

```
Introduction - before beginning of Annexes (start_page_number, end_page_number)  ->  (13, 67)
```

That range is the ground-truth for "where the real body content lives".

## What the script checks

For every document it:

1. reads the human-set body page range from source metadata;
2. reads the classified table of contents (`sys_toc_classified`) — the same
   "Contents" section tags shown in the document viewer;
3. flags every section whose page falls inside the body range but whose section
   type is **not** in the default-included set.

A flagged section is body content that would be accidentally excluded from
default search.

Both inputs come from the Postgres sidecar table `docs_<data_source>` (via
`PostgresClient.fetch_all_docs()`): the page range from the
`src_doc_raw_metadata` JSONB column, the section tags from
`sys_data -> 'sys_toc_classified'`. Qdrant is not used — its document payload
carries only `map_*` / `tag_*` fields.

### Verdicts

- **pass** — every section inside the body range has a default-included type.
- **fail** — at least one section inside the body range has an excluded type.
- **skipped** — the document has no body range or no classified TOC.

> Note: `introduction` is not in the default-included set, so a section still
> tagged `introduction` inside the body range is reported as a (real) finding —
> that introduction content is excluded from default search.

## Usage

```bash
# Check all documents in a data source
python tests/evaluation/section_inclusion/check_included_section_types.py --data-source wfp

# Check a sample of N documents
python tests/evaluation/section_inclusion/check_included_section_types.py --records 20

# Check a single document by doc id
python tests/evaluation/section_inclusion/check_included_section_types.py --file-id <id>

# Custom output path
python tests/evaluation/section_inclusion/check_included_section_types.py --output results.xlsx
```

Requires Postgres with the target table (`docs_<data_source>`) and the usual
`.env`. It is a standalone script, not a pytest test. Easiest way to run it is
inside the pipeline container, which already has the dependencies:

```bash
docker compose exec -T pipeline python \
  tests/evaluation/section_inclusion/check_included_section_types.py --data-source wfp
```

## Output

- Console: per-document `FAIL` lines plus a summary (pass/fail/skipped counts and
  a tally of which excluded section types show up inside body ranges).
- Excel (`.xlsx`, default `logs/section_inclusion_eval.xlsx`) with one row per
  document: `doc_id`, `title`, `metadata_range`, `range_start`, `range_end`,
  `sections_in_range`, `num_excluded`, `excluded_section_types`,
  `excluded_details`, `status`, `reasons`.

## Tests

Pure logic (range parsing, TOC parsing, exclusion detection, verdict) is unit
tested in
[`tests/unit/test_check_included_section_types.py`](../../unit/test_check_included_section_types.py).
