# TOC Validator

The **TOC Validator** (Admin → TOC Validator) checks that document body content is
not accidentally hidden from search because of how its sections are tagged.

## Why this matters

Search has a **content type** filter (Search / Content settings). By default it only
returns chunks whose section type is one of the "real content" types:

```
executive_summary, context, methodology, findings, conclusions, recommendations, other
```

Every other section type — `front_matter`, `acronyms`, `annexes`, `appendix`,
`bibliography`, `introduction` — is **excluded by default**.

Section tagging is automatic (done at upload by the TOC classifier). If a section
that is really part of the report body is mis-tagged as, say, `annexes`, that content
silently disappears from default search results. Users never see it and never know
it is missing.

Each document also carries a **human-set** page range in its source metadata:

```
Introduction - before beginning of Annexes (start_page_number, end_page_number)  ->  (14, 56)
```

That range is the ground truth for "where the real body content lives".

## What the validator checks

For each selected document it:

1. reads the human-set body page range from the document's source metadata;
2. reads the section tags from the classified table of contents (the same tags shown
   in the **Contents** view of a document);
3. flags every section whose page falls inside the body range but whose section type
   is **not** in the default-included set.

A flagged section is body content that would be excluded from default search.

> The validator only **checks** the current classification. It never re-runs the
> classifier and never changes tags. Fixing a bad tag is a deliberate manual step —
> see [Fixing a bad classification](#fixing-a-bad-classification).

### Verdicts

| Verdict | Meaning |
|---|---|
| **Pass** | Every section inside the body range uses a default-included type. |
| **Fail** | At least one section inside the body range uses an excluded type. |
| **Skipped** | The document has no body page range, or no classified contents. |
| **Not tested** | The document has not been validated yet. |

## Using the screen

1. Open **Admin → TOC Validator** (superuser only).
2. Optionally filter the list by title.
3. Select documents with the row checkboxes, the header checkbox (selects the current
   page), or **Select all** (selects every document matching the current filter).
4. Click **Run validation**. Results are saved against each document, so they persist
   and are shown the next time the screen is opened.
5. Rows whose verdict was added or changed by the run are highlighted and marked
   **updated**.

Each row has **Metadata** and **Contents** links, the same as the Documents Library,
so a flagged result can be checked against the actual document.

## Interpreting results

A **Fail** means the classifier's labels disagree with the human page range. It does
not by itself say which of the two is wrong — the page range could be off, just as
the tag could be. Use the **Contents** and **Metadata** views to decide.

Two patterns are worth separating:

* **`introduction` flagged across most documents.** This is systemic, not per-document
  mis-tagging: the body range starts at the introduction, and `introduction` is not in
  the default-included set (nor is it offered as a filter option in Search settings).
  The fix is a decision about the defaults, not about individual documents.
* **`annexes` / `acronyms` / `bibliography` / `front_matter` inside the body range.**
  These are genuine mis-tags worth investigating per document — for example a report
  whose *Findings* and *Recommendations* chapters were labelled `annexes` because their
  headings contained cross-references such as "(EQs 1-5, Annex 8)".

## Fixing a bad classification

From a flagged row, open **Contents**, correct the section type, and save. Editing the
classification automatically re-validates that document so the verdict updates.

## Where results are stored

Results are stored per document in the data source's document row, under the
`sys_toc_validation` field (recorded alongside the timestamp and the user who ran the
check). No database migration is required — the per-data-source `docs_<source>` tables
create `sys_*` fields on write.

## Running the same check offline

The identical validation logic is available as a standalone script for bulk reporting
across a whole data source, producing an Excel report:

```bash
python tests/evaluation/section_inclusion/check_included_section_types.py --data-source wfp
```

See `tests/evaluation/section_inclusion/README.md`. Both the screen and the script use
the same logic in `pipeline/validation/section_inclusion.py`.
