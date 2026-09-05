# UNEG Data Refresh Plan

Goal: bring the UNEG data source up to date with the live UNEG repository, remove
the duplicates that have crept into the tree, and leave the system in a state
where an unattended weekend job picks up new documents. Documents whose content
has not changed must not be re-parsed, re-summarised or re-embedded, but their
metadata must still be refreshed.

This plan is based on measurements taken on 2026-09-05 against the demo data
tree, the live UNEG site, and the code in this repo and the private integration
repo. Where a claim comes from reading code rather than running it, it is
labelled "code reading" and has a verification step.

---

## 1. Where things stand

### 1.1 The data tree (`/Volumes/disco1/data/evidencelab-ai/data-files/data/uneg`)

| Measure | Value |
|---|---|
| Metadata JSON files under `pdfs/` | 15,790 |
| Distinct UNEG node IDs | 14,835 |
| Nodes with a document on disk | 13,547 |
| Nodes with only an `.error` file | 1,230 |
| Nodes with more than one JSON (multi-report evaluations) | 597 |
| Document files (pdf / docx / doc) | 13,113 / 2,602 / 1,461 |
| Distinct document checksums (sha256) | 14,970 of 17,176 files |
| Duplicate groups / extra copies | 2,054 / 2,206 |
| Duplicate groups within one node / across years / across agencies | 1,774 / 127 / 29 |
| `.error` files | 2,234 |
| JSONs by `download_date` month (2026) | Jan 1,737 · Feb 2,909 · Mar 11,144 |
| Newest documents | WFP 2026, downloaded 2026-03-25 |
| Agency folders | 33 (both `UN Women` and `UN_Women` exist) |
| `parsed/` tree | 352 GB |
| Download cache (`cache/html`, `cache/pdfs`) | 15,577 pages, 22,941 files |

The live site lists **15,570** documents (years 1985 to 2027), so the tree is
roughly 700 to 1,000 nodes behind, plus whatever metadata was edited since March.

The duplicate picture: most duplicate groups are the same bytes saved twice for
one node (a `.pdf` and a `.docx` with identical content, or "Main Report" and
"Report 2" pointing at the same file). The cross-year and cross-agency groups
are the same evaluation listed under two nodes. The scanner marks these
`is_duplicate` by checksum at scan time, but the files, records, chunks and
vectors all still exist.

### 1.2 What the March refresh did (prior art already in the repo)

The tree is the product of a refresh done in February and March 2026:

1. A full re-scrape into `data/uneg-new` (15,407 pages, 16 to 22 Feb, roughly
   7,000 pages per day with Selenium).
2. `scripts/maintenance/compare_downloads.py` produced `uneg-comparison.json`
   (14,317 shared nodes; 7,276 identical PDFs, 105 changed, 628 only-new, 5,143
   error-state changes).
3. `scripts/maintenance/update_uneg_data.py --wet-run` on 13 March applied
   25,197 file actions (delete 5,468 duplicate PDFs, replace 10,952 JSONs, copy
   243 new-node PDFs, 522 newly available PDFs, 80 changed PDFs). Its log is
   `uneg-update-results.json`.
4. Local DB dumps tagged `uneg-reload-1` were taken on 25 March.

Those two scripts are the right skeleton. Their weaknesses: they match by node
ID parsed from the filename only, they compare whole JSONs (so every node shows
as changed because `download_date` and `filepath` differ), and
`update_uneg_data.py` hardcodes the three reassigned nodes from March.

### 1.3 The downloader (private repo `dividor/evidencelab-ai-integration`)

`config.json` points the download stage at
`pipeline/integration/evidencelab-ai-integration/uneg/download.py`. That
directory is **empty** in this checkout, so the orchestrator's download step
cannot run here today. Populated clones exist in sibling checkouts; the newest
is under `~/git/OLDevidencelab`.

State of the integration repo:

- `origin/main` is at 2026-03-07.
- Branch `fix/uneg-other-links-fallback` has 8 unmerged commits (2026-03-15 to
  03-20): cap to one primary document per evaluation, dedupe by node ID,
  `fallback_urls`, Selenium retry on 403, plus a new `unmandates` downloader.
  The March tree was produced by this branch (1,386 of 2,000 sampled JSONs carry
  `fallback_urls`, which only exists there).
- The `OLDevidencelab` working copy has 37 uncommitted lines: a direct
  `/get-download-file/{node_id}` fallback and a skip for empty year/agency
  combinations.

Two behaviours matter for a refresh:

- Everything goes through Selenium: listing pages, "Show More" clicks, every
  node page.
- **Cached HTML wins.** `get_page_html` returns the cached page unless
  `--force-download` or `--force-retry-errors` is set. A refresh run that
  keeps `cache/html` would silently re-read March metadata for 15,577 nodes.
  Any refresh must either clear the HTML cache or run with the cache bypassed.

### 1.4 What changed on the UNEG site

Measured by fetching `https://www.unevaluation.org/node/17480` and the listing
with plain HTTP (no JavaScript):

- **"AI-generated content" badge.** The Report Details rows for Type,
  Crosscutting Types, Theme/s and SDG/s now carry an "AI-generated content"
  label inside the label cell. The scraper's `get_text(strip=True)` glues it to
  the label, producing keys such as `AI-generated contentType` and
  `AI-generated contentCrosscutting Types`. These already appear in the March
  tree (58 and 37 of 2,000 sampled JSONs). Consequences in the current scraper:
  - `label_lower == "type"` no longer matches, so `evaluation_type` depends
    solely on the `.detail-meta-item.type` selector.
  - `theme` and `sdg` still match by substring, but the provenance (site says
    these are AI-generated) is dropped.
  - Unknown labels are stored verbatim, so raw metadata has inconsistent key
    names for the same concept across documents.
- **Fields present on the page** (labels exactly as rendered): Year Published,
  Type, Crosscutting Types, Theme/s, Joint, Partner/s, SDG/s, Managed by
  Independent Evaluation Office, Geographic Scope, Country/ies, Related Link,
  Download Link. Other documents also show Consultant name, Agency Focal Point,
  Focal Point Email. Multi-value fields are delimited by ` | `.
- **Download button** is now `a.doc-link` with a `data-nid` attribute pointing
  at `/get-download-file/{nid}`; the older `external-popup-link` class was
  absent on the sample page. The uncommitted local patch handles this.
- **No change signal from the server.** Node pages return
  `Cache-Control: no-store`, no `Last-Modified`, no `ETag`, no visible modified
  date. Drupal JSON:API is not exposed. "Has this node changed" can only be
  answered by re-reading the page.
- **Selenium is not required for crawling.** The listing paginates with
  `?page=N` (18 rows per page, about 865 pages for 15,570 docs) and accepts
  `sort_by=field_date&sort_order=DESC` on a plain GET; pages 0, 1, 2 returned
  disjoint node sets. Node pages render the full metadata table in static HTML.
  Selenium remains useful as a fallback for 403s and the third-party pages
  (wedocs, wfp.org).
- A `HEAD` on `/get-download-file/{nid}` returns `content-length` and a
  `content-disposition` filename. That is a cheap way to detect a changed file
  without downloading it.

### 1.5 How the pipeline keys and reuses work (code reading)

- `doc_id = uuid5(NAMESPACE_URL, "data/uneg/pdfs/<agency>/<year>/<file>")`. The
  filename is `sanitize(title)[:100]_<node_id>.<ext>`. Chunk IDs are
  `uuid5(doc_id + index)`. The parsed folder is
  `parsed/<agency>/<year>/<file stem>/`. So **file path is the identity for
  everything downstream**: Postgres rows, Qdrant points, chunk IDs, parsed
  output, summaries, tags.
- The parsed folder holds the parse output (`.md`, `.json`, `chunks/`,
  `images/`, `tables/`, `toc.txt`), the summary (`llm_summary.txt`), a
  thumbnail, and `qdrant.zip` containing every chunk point with vectors and
  payload plus a document snapshot with its embedding (`indexer.py:662`).
  Nothing in the repo reads `qdrant.zip` back; it is write-only today. The
  folder also contains a symlink to the source file using an old absolute path
  (`/Users/matthewharris/Data/evidencelab/...`), so moving folders needs care.
- The scanner stores `sys_file_checksum` and `sys_metadata_checksum` and
  classifies each JSON as new / file changed / metadata changed / both /
  unchanged. On a metadata-only change it overwrites Postgres (`upsert_doc`)
  and batch-upserts the Qdrant document point, keeping the status. On a file
  change it does the same; nothing consumes `sys_last_change_type`.
- No table other than `docs_uneg` and `chunks_uneg` stores document IDs
  (checked all Alembic migrations). External references (shared URLs, MCP
  citations, saved briefs) may embed IDs, but nothing in the database enforces
  them.

Three gaps follow, each to be verified with a unit test before we rely on it:

| Gap | Effect | Evidence |
|---|---|---|
| A. Chunk payloads not updated | `chunks_uneg` points carry denormalised `src_*`, `map_*`, `tag_*`, `sys_language` (`indexer._build_doc_payload_fields`). Metadata edits never reach them, so search filters keep matching old values. | No writer to chunks in the scanner. Precedent for the fix: `scripts/fixes/fix_wfp_metadata_deltas.py`, `scripts/maintenance/backfill_multivalue_fields.py`. |
| B. Document point replaced, not merged | `_flush_batch` upserts a whole `PointStruct` with `vector={}` and a scan-only payload. The indexer stores a document-level vector on that point, the tagger writes `tag_*` via `set_payload`, and `is_duplicate` lives only there. A metadata-only rescan would drop all three. | `scanner._flush_batch`, `indexer.py:826`, `tagger_processor.py:175`. `Database.update_document` already uses `set_payload` and is the safe alternative. |
| C. Changed file keeps its status | Content changes are recorded but never reprocessed. | `_resolve_effective_status` keeps the existing status. |

Production (`evidencelab.ai`) runs with the pipeline service disabled.
Ingestion happens locally and the databases are shipped with
`scripts/sync/db/*`. Every refresh, including the weekly one, ends with a DB
sync rather than a remote pipeline run.

---

## 2. Strategy

### 2.1 The options

**Option A. In-place merge (the March approach, tightened).** Re-read metadata
for every node, download only new or changed files, overwrite JSONs at their
existing paths. Cheapest in compute, but it inherits the tree's history:
duplicates stay unless pruned separately, the multi-report nodes keep whatever
the old downloader chose, and reassigned nodes need special handling.

**Option B. Fresh download decides what should exist; checksum decides what to
reuse.** Do a complete fresh download into a new tree with the current
downloader (one primary document per node, dedupe by node ID). The fresh tree
is the canonical set. Then reconcile it against the existing tree and database
by file checksum:

- Fresh file whose checksum matches an existing document: **adopt the existing
  document** (keep its path, `doc_id`, parsed folder, summary, tags, chunks and
  vectors) and write the fresh metadata JSON over its existing JSON. The fresh
  copy of the file is discarded. Nothing downstream runs except the metadata
  propagation from gaps A and B.
- Fresh file with no checksum match: **new document** at the fresh path; full
  pipeline.
- Existing document that no fresh file matched: **retire it**. This set is
  exactly the duplicates, the secondary reports the new downloader no longer
  fetches, and the nodes removed from the site. Files are moved to a
  `retired-<date>/` tree and records pruned with `prune_orphaned_docs.py`
  (dry-run first; see open decisions).

This gives the "start again" semantics (clean canonical set, no duplicates,
consistent metadata) while reusing every prior processing artefact, because
reuse happens at the level of document identity instead of copying files.

**Option C. Fresh tree with fresh identities, reuse only parsed output.** Copy
the old parsed folder next to the new file when the checksum matches, then run
summarise, tag and index again for those documents. This is the literal "copy
previous parsed or do again". It costs LLM calls and embeddings for roughly
13,500 documents, needs a loader that rewrites `doc_id`, chunk IDs, payload
`doc_id` and `sys_parsed_folder` (none exists), breaks every external link
that embeds a document ID, and moves a large share of 352 GB. The only thing it
buys over Option B is new filenames for documents whose titles changed.

**Recommendation: Option B.** It is the user's instinct (fresh everything,
reuse by checksum) applied at the identity level rather than the file level.
If a document's title changed on the site, its filename stays old but the
`map_title` and every payload get the new title, which is what users see.

### 2.2 Classification after reconciliation

| Class | Detection | Action |
|---|---|---|
| Adopted, unchanged | Checksum match, normalised metadata equal | Nothing |
| Adopted, metadata changed | Checksum match, normalised metadata differs (ignore `download_date`, `filepath`, `filename`, `file_size`, `fallback_urls`) | Overwrite JSON at existing path; scanner updates Postgres, doc payload and chunk payloads |
| Adopted, file changed | Same node ID, different checksum, existing document at that node | Copy the fresh file over the existing path, overwrite JSON; scanner resets status to `downloaded`, deletes old chunks; pipeline re-parses |
| New | No checksum match and no existing document for the node | Keep at fresh path; full pipeline |
| Previously errored, now available | Existing node has only `.error`, fresh has a file | Same as new; delete `.error` |
| Retired | Existing document matched by nothing in the fresh tree | Move files to `retired-<date>/`, prune records |
| Reassigned node ID | Same node ID, different agency or year in fresh vs existing | Existing goes to retired, fresh is new |

### 2.3 The weekend job

Because the site offers no change feed, the weekly job is a smaller version of
the same loop, requests-first and unattended:

1. Crawl the full listing sorted by date (about 865 GETs, ~15 minutes) to get
   the complete set of node IDs. Diff against the node IDs in the tree.
2. Fetch node pages for new IDs, download their documents (Selenium fallback
   only if needed), place them in the tree. Optionally fetch every node page
   (~15,600 GETs, 4 to 5 hours) so metadata edits are also picked up; this
   fits inside a weekend window and can be a monthly flag instead.
3. Run the reconcile step (same script as the one-time refresh, same checksum
   rules) so a re-uploaded document or a new duplicate is handled the same way.
4. Run the pipeline with `--skip-download` so only new and changed documents
   go through parse, summarise, tag and index.
5. Dump Postgres and Qdrant, upload, restore on production, and diff the
   counts against the previous run.
6. Write a run report (counts per class, failures, elapsed) to
   `data/uneg-refresh-logs/<date>.json` and exit non-zero on any failure so
   the scheduler surfaces it.

Everything in that loop already exists in pieces; the work is to make each
piece idempotent, non-interactive, and driven by one entry point.

---

## 3. Phases

### Phase 0. Consolidate and fix the downloader (integration repo)

1. Merge `fix/uneg-other-links-fallback` into `main` (it produced the March
   tree). Commit the 37 uncommitted lines from the `OLDevidencelab` working
   copy on top.
2. Clone the integration repo into `pipeline/integration/` in this checkout so
   the configured download command exists.
3. Fix label handling for the "AI-generated content" badge: strip the badge
   before matching, record provenance in a companion field (for example
   `ai_generated_fields`), promote Crosscutting Types, Related Link, Managed by
   IEO, Agency Focal Point, Focal Point Email and Consultant name to stable
   snake_case keys, and normalise ` | ` to `; `.
4. Add a requests-first path with Selenium fallback: `--list-only` (listing
   crawl to `node_index.json`), `--metadata-only` (node pages plus `HEAD` on
   the download endpoint), `--nodes <file>` (restrict to listed node IDs),
   `--no-html-cache` (bypass cached pages for refresh runs).
5. Unit tests for the parser against two saved HTML fixtures: a March-cache
   page (old layout) and a page fetched now (badge layout). Same normalised
   keys must come out of both.

### Phase 1. Baseline and backups

1. Record production counts: documents and chunks per status in `docs_uneg`
   and both Qdrant collections, plus the list of doc IDs. Save to
   `uneg-refresh-<date>/baseline.json`.
2. Take Postgres and Qdrant dumps of production and of the local working DB.
3. Snapshot the data tree (`rsync` to `uneg-pre-refresh-<date>/`).
4. Build a checksum index of the existing tree once
   (`path, sha256, node_id, doc_id`) and compare it with `sys_file_checksum`
   in Postgres to find records whose on-disk file no longer matches. The 80
   PDFs replaced in March are the first suspects; they join the "file changed"
   set if the pipeline never re-parsed them.

### Phase 2. Fresh download

1. Clear or bypass `cache/html`. Keep `cache/pdfs` (it saves bandwidth and the
   checksum decides reuse anyway).
2. Run the full download into `data/uneg-fresh-<date>/` with the consolidated
   downloader. Expect 2 to 3 days with Selenium as in February; the
   requests-first path from phase 0 should cut that substantially, but that is
   unmeasured until it runs.
3. Sanity-check the fresh tree: node count against the listing total,
   error-only count against February (4,911 errors then), and a duplicate
   check by checksum, which should be near zero given the one-per-node cap.

### Phase 3. Reconcile

1. Replace `update_uneg_data.py` with `scripts/maintenance/uneg_reconcile.py`
   (dry-run by default, JSON action log, no hardcoded node lists). Inputs: the
   existing tree, the fresh tree, the checksum index from phase 1, and the
   Postgres checksums. Output: the classification from section 2.2 and the
   file actions to realise it.
2. Rules: never rename an existing file; write fresh JSON over the existing
   JSON path with `filename` and `filepath` rewritten to the existing file;
   copy changed files over the existing path; place new files at their fresh
   path; move retired files (document, JSON, `.error`, parsed folder) into
   `retired-<date>/` rather than deleting.
3. Dry-run, review the class counts and a sample of each class, then wet-run.
4. Unit tests with a small synthetic pair of trees covering every class in
   section 2.2, including the pdf/docx same-bytes case and a reassigned node.

### Phase 4. Pipeline fixes (this repo, with unit tests)

1. **Gap B**: in `ScanProcessor`, when the document already exists, apply the
   scan payload with `set_payload` (merge) instead of replacing the point.
   Test: an existing point with a vector and `tag_sdg` keeps both after a
   metadata-only rescan.
2. **Gap A**: add `Database.propagate_doc_fields_to_chunks(doc_id, fields)`
   using `set_payload` with a `doc_id` filter, called from the scanner on
   `metadata` and `both` change types for `src_*`, `map_*`, `sys_language`.
   Test: chunk payload reflects the new `map_country` after rescan.
3. **Gap C**: on `file` or `both`, set `sys_status` to `downloaded`, delete the
   old chunks and clear `sys_parsed_folder` so the document is re-parsed.
   Test: status transition and chunk deletion happen only for file changes.
4. Scanner tests for the classification paths (`tests/unit/test_scan.py`
   covers checksums and path helpers but not `_evaluate_existing`).
5. `config.json` field mapping: decide which new fields surface. Candidates:
   `crosscutting_types` as a filter, `related_link` in the metadata panel, an
   "AI-generated metadata" indicator. Multi-value handling follows
   `docs/plans/multivalue-fields-to-lists.md`.

### Phase 5. Local ingestion run

1. Restore the production dumps from phase 1 into the local stack so the run
   starts from the real state (disk path for the DB mount, not `/tmp`).
2. `./scripts/pipeline/run_pipeline_host.sh --data-source uneg --skip-download`.
   The scan summary must match the reconcile classes: new = new count, file
   changed = changed count, metadata changed = adopted-changed count.
3. Confirm only new and file-changed documents move through parse, summarise,
   tag and index. Spot-check an adopted-changed node in Postgres, the document
   payload (vector and `tag_*` still present) and a chunk payload.
4. `prune_orphaned_docs.py --source uneg` dry-run, then `--confirm` for the
   retired set.

### Phase 6. Ship to production

1. Dump local Postgres and Qdrant, upload with
   `scripts/sync/db/sync_backup_to_remote.py`, restore on `evidencelab.ai`.
   Ship changed paths under `pdfs/` and `parsed/` with
   `scripts/sync/files/sync_azure.py` using the reconcile action log as the
   file list.
2. Re-run the phase 1 count queries on production and diff against the
   baseline.
3. Update `docs/overview/data.md` and add the runbook to
   `docs/admin/database-maintenance.md`.

### Phase 7. Weekend job

1. `scripts/maintenance/uneg_weekly_refresh.py`: one entry point that runs the
   loop in section 2.3 with `--dry-run`, `--metadata-pass` (all node pages
   versus new nodes only), `--skip-sync` flags, writes the run report, and is
   safe to re-run after a failure (every step is idempotent because the
   reconcile step is checksum-driven).
2. Schedule it on the ingestion machine for Saturday early morning, with
   `--metadata-pass` on the first weekend of each month. Alert on non-zero
   exit.
3. First two runs supervised; compare the run reports against manual counts.
4. Unit tests for the report writer and the node-ID diff; the download and
   pipeline steps are covered by their own tests.

---

## 4. Verification checklist

- Parser fixture tests pass for both page layouts.
- Reconcile tests cover every class, including same-bytes pdf/docx and a
  reassigned node.
- Scanner tests cover new, metadata-only, file-changed and both, and assert
  vector, `tag_*` and `is_duplicate` survive a metadata-only rescan.
- Reconcile totals reconcile: adopted + new + retired equals the union of
  existing documents and fresh files.
- Phase 5 scan summary matches the reconcile classes.
- After phase 5 the checksum duplicate count in the tree is zero (or only the
  documented exceptions).
- Production counts after restore match local.
- The first weekend run's report matches a manual listing diff.

## 5. Risks and open decisions

- **Retired documents.** Option B retires duplicates, secondary reports and
  documents removed from the site in one set. Decide whether secondary reports
  of multi-report evaluations (597 nodes) should be kept as documents. If yes,
  the reconcile step keeps existing documents whose node still exists in the
  fresh tree even when their checksum was not re-downloaded.
- **External links that embed document IDs** keep working under Option B for
  adopted documents and break only for retired ones.
- **Volume of "metadata changed"** will be large the first time because the
  scraper fix renames keys. Chunk payload updates are `set_payload` calls
  batched per document; run them off-peak on production.
- **Rate limiting and 403s.** Keep a polite delay and the Selenium fallback.
- **HTML cache.** A refresh that keeps `cache/html` re-reads March pages. The
  `--no-html-cache` flag in phase 0 exists for this; the weekly job always
  sets it.
- **Reassigned node IDs** happened three times in March. The reconcile step
  flags "same ID, different agency or year" instead of overwriting.
- **New fields in the UI** are a product call (crosscutting types, related
  link, AI-generated indicator).
- **Integration repo hygiene.** The newest downloader code is on an unmerged
  branch plus an uncommitted patch in a sibling checkout. Phase 0 fixes that
  and must come first or the refresh cannot be reproduced.

## 6. Effort estimate

| Phase | Wall clock | Hands-on |
|---|---|---|
| 0 Downloader consolidation and fixes | 1 to 2 days | yes |
| 1 Baseline, backups, checksum index | half a day | partly |
| 2 Fresh download | 1 to 3 days | no |
| 3 Reconcile script and run | 1 to 2 days | yes |
| 4 Pipeline fixes and tests | 1 to 2 days | yes |
| 5 Local ingestion | hours to a day depending on new-doc count | no |
| 6 Ship to production | 2 to 4 hours | yes |
| 7 Weekend job | 1 day plus two supervised runs | yes |
