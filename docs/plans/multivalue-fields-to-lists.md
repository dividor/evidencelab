# Plan: Multi-value fields as lists in Qdrant, strings in PostgreSQL

## Problem

Multi-value fields (`country`, `region`, `theme`, `document_type`, `language`, `topic`) are stored as **semicolon-separated strings** in Qdrant (e.g. `"Nepal; India"`). This breaks Qdrant's native faceting API — it counts `"Nepal; India"` as a single facet value instead of two separate values. The app code has workarounds (`_split_multivalue`, `expand_multivalue_filter`) that try to fix this at query time, but they produce incorrect counts and filtering behaviour.

**The correct model:**
- **Qdrant**: lists → `["Nepal", "India"]` — native faceting counts each element
- **PostgreSQL**: strings → `"Nepal; India"` — TEXT columns, for display/export

This applies to **both `map_` and `src_` fields** since both can be used as facet/filter fields.

## Current data flow

```
Downloader (JSON metadata)
    ↓ strings: "Nepal; India"
Scanner Mapping (_split_if_multival)
    ↓ map_ fields: ["Nepal", "India"]  (lists — correct for Qdrant)
    ↓ src_ fields: "Nepal; India"      (raw string — NOT split)
Database Layer
    ↓ Qdrant: map_ as list, src_ as string
    ↓ PostgreSQL: map_ as list → psycopg2 serializes as {Nepal,India} (BROKEN)
```

**Issues at each stage:**

1. **Downloaders** produce semicolon-joined strings in JSON. This is fragile — if the scanner mapping's `_split_if_multival` isn't applied, the string goes through as-is.
2. **Scanner mapping** splits `map_` fields but NOT `src_` fields (`_build_src_fields` passes raw values).
3. **PostgreSQL** receives Python lists for `map_` fields and serializes them as array literals `{val1,val2}` — PR #199 (open, not yet merged) fixes this by coercing lists to `"; "`-joined strings before INSERT.
4. **Existing data** in Qdrant for all 19,408 UNEG docs and World Bank docs has strings, not lists, for `map_` fields. And `src_` multi-value fields are strings everywhere.

## Affected fields per datasource

### UNEG (UN Humanitarian Evaluation Reports)
| Core field | map_ field | src_ field | Multi-value? |
|---|---|---|---|
| document_type | map_document_type | src_evaluation_type | Yes |
| country | map_country | src_country | Yes |
| language | map_language | src_language | Yes |
| region | map_region | src_region | Yes |
| theme | map_theme | src_theme | Yes |

### World Bank
| Core field | map_ field | src_ field | Multi-value? |
|---|---|---|---|
| document_type | map_document_type | src_majdocty | Yes |
| country | map_country | src_count | Yes |
| region | map_region | src_admreg | Yes |
| theme | map_theme | src_theme | Yes |
| language | map_language | src_available_in | Yes |
| topic | map_topic | src_subtopic | Yes |

## Implementation plan

### Step 0: Back up existing data

Before making any changes, dump both Qdrant and PostgreSQL databases using the existing sync scripts.

```bash
# UNEG backups
python scripts/sync/db/dump_qdrant.py \
    --data-source uneg \
    --output /Volumes/disco1/data/evidencelab-ai/db-backups/ \
    --prefix pre-multi-val-

python scripts/sync/db/dump_postgres.py \
    --data-source uneg \
    --output /Volumes/disco1/data/evidencelab-ai/db-backups/ \
    --prefix pre-multi-val-

# World Bank backups
python scripts/sync/db/dump_qdrant.py \
    --data-source worldbank \
    --output /Volumes/disco1/data/evidencelab-ai/db-backups/ \
    --prefix pre-multi-val-

python scripts/sync/db/dump_postgres.py \
    --data-source worldbank \
    --output /Volumes/disco1/data/evidencelab-ai/db-backups/ \
    --prefix pre-multi-val-
```

**Verify** backup files exist and are non-empty before proceeding.

### Step 1: Create fix script for existing Qdrant data

**New file:** `scripts/fixes/fix_multivalue_to_list.py`

This script converts all multi-value `map_*` and `src_*` fields from semicolon-separated strings to proper lists in Qdrant. It does NOT touch PostgreSQL (strings are correct there).

**Logic for each point in Qdrant:**
```
For each field in the point's payload:
  if field is a known multi-value map_ or src_ field:
    if value is a string containing "; ":
      → split on "; " → store as list
    elif value is a non-empty string (single value):
      → wrap as [value]
    elif value is already a list:
      → skip
```

**Known multi-value fields to process:**
- UNEG: `map_country`, `map_region`, `map_theme`, `map_document_type`, `map_language`, `src_country`, `src_region`, `src_theme`, `src_evaluation_type`, `src_language`
- World Bank: `map_country`, `map_region`, `map_theme`, `map_document_type`, `map_language`, `map_topic`, `src_count`, `src_admreg`, `src_theme`, `src_majdocty`, `src_available_in`, `src_subtopic`

**Collections to process:** `documents_{ds}` and `chunks_{ds}` for each datasource.

**Flags:**
- `--data-source` (required): e.g. `uneg`, `worldbank`
- `--dry-run`: show what would change without applying
- `--collection`: `chunks`, `docs`, or `all`
- `--fields`: optional comma-separated list to limit which fields to fix (default: all known multi-value fields for the datasource)

**Pattern:** Follow the existing `fix_country_concatenation.py` pattern — scroll in batches of 500, collect fixes, apply with `set_payload` in batches of 50 with retry logic.

**Derive field lists from config.json** rather than hardcoding — read `field_mapping` and `_SCALAR_FIELDS` to determine which fields are multi-value. This way any future datasource gets correct behaviour automatically.

### Step 2: Update UNEG downloader to output lists

**File:** `pipeline/integration/evidencelab-ai-integration/uneg/download.py`

Currently the downloader joins multi-value fields with `"; "`:
```python
# Current (lines ~1347-1349):
value = "; ".join([link.get_text(strip=True) for link in links])

# Current (lines ~1388-1390):
value = items_elem.get_text(separator="; ", strip=True)
```

**Change to:** Output lists for fields that map to multi-value core fields (country, region, theme, document_type, language). The downloader knows which fields are multi-value because they come from multiple HTML `<a>` links or multi-element text nodes.

```python
# New — when multiple links found:
if links:
    values = [link.get_text(strip=True) for link in links]
    value = values if len(values) > 1 else values[0]
else:
    value = value_elem.get_text(strip=True)  # Single value, keep as string
```

For `get_text(separator="; ")` cases (plain text with multiple children), split to list:
```python
parts = [p.strip() for p in value_elem.stripped_strings]
value = parts if len(parts) > 1 else (parts[0] if parts else "")
```

This means the JSON metadata files will contain lists for multi-value fields. The scanner's `_split_if_multival` will pass lists through unchanged (line 116: `if isinstance(value, str)` — lists skip this). And `_build_src_fields` will also pass lists through to Qdrant `src_` fields.

### Step 3: Update World Bank downloader to output lists

**File:** `pipeline/integration/evidencelab-ai-integration/worldbank/download.py`

Currently `normalize_metadata()` joins dict-of-dicts with `"; "`:
```python
# Current (line ~208):
metadata[key] = "; ".join(parts)
```

**Change to:** Output list instead of joined string for multi-entry fields:
```python
# New:
metadata[key] = parts if len(parts) > 1 else parts[0]
```

Similarly for `SEMICOLON_DELIMIT_FIELDS` (subtopic, teratopic, historic_topic) — instead of converting commas to semicolons and joining, split into a list:
```python
# Current:
metadata[key] = "; ".join(p.strip() for p in metadata[key].split(",") if p.strip())

# New:
parts = [p.strip() for p in metadata[key].split(",") if p.strip()]
metadata[key] = parts if len(parts) > 1 else (parts[0] if parts else metadata[key])
```

### Step 4: Update scanner mapping `_build_src_fields` to split strings

**File:** `pipeline/processors/scanning/scanner_mapping.py`

Currently `_build_src_fields` passes raw values through. If a downloader still outputs strings (e.g. an older JSON file being re-scanned), the `src_` field would remain a string in Qdrant.

**Add a defensive split** in `_build_src_fields` for `src_` fields that correspond to multi-value core fields. This requires knowing the reverse field mapping to check if the source field maps to a multi-value core field.

```python
def _build_src_fields(self, raw_metadata, reverse_mapping=None):
    src_fields = {}
    for key, value in raw_metadata.items():
        sanitized = sanitize_source_key(str(key))
        ...
        # If this src field maps to a multi-value core field, split it
        core_field = reverse_mapping.get(key) if reverse_mapping else None
        if core_field and core_field not in self._SCALAR_FIELDS:
            value = self._split_if_multival(core_field, value)
        src_fields[f"src_{sanitized}"] = value
    return src_fields
```

This is a safety net — ensures that even if legacy JSON files with strings are re-scanned, `src_` fields in Qdrant get lists. The reverse mapping is already built in `_build_reverse_mapping()` (line 157).

### Step 5: Merge PR #199 (PostgreSQL list coercion)

**PR #199** (`fix/map-field-list-coercion` → `rc/v1.1.0`) adds one line to `postgres_client_docs.py`:
```python
"; ".join(v) if isinstance(v := map_fields.get(key), list) else v
```

This ensures that when `map_` fields are lists (as they should be for Qdrant), PostgreSQL still gets clean `"; "`-joined strings in TEXT columns.

**Status:** Open, targeting `rc/v1.1.0`. Needs to be merged before or alongside this work.

**Note:** This only coerces `map_` fields. `src_` fields are stored in PostgreSQL's `src_doc_raw_metadata` JSONB column, which handles JSON arrays natively — no coercion needed there.

### Step 6: Add downloader documentation

**File:** `docs/admin/pipeline-configuration.md` (update existing section)

The existing docs cover download stage configuration (command, args, placeholders) but do NOT document:
- The expected format of JSON metadata files produced by downloaders
- How multi-value fields should be represented (lists vs strings)
- The relationship between JSON metadata → scanner mapping → Qdrant/PostgreSQL

**Add a new section** documenting:

1. **Downloader JSON output format**: Each document produces a `.json` metadata file alongside the downloaded PDF. The metadata file contains key-value pairs where:
   - **Single-value fields** (title, year, organization, pdf_url, report_url) are strings
   - **Multi-value fields** (country, region, theme, document_type, language, topic) are **lists** of strings, e.g. `["Nepal", "India"]`
   - Single-element multi-value fields can be either a string or a single-element list

2. **Field mapping**: How `field_mapping` in `config.json` maps source field names to core field names, and how `_SCALAR_FIELDS` determines which fields are treated as scalar vs multi-value.

3. **Data flow**: How metadata flows from JSON → scanner mapping → Qdrant (lists) and PostgreSQL (strings).

### Step 7: Legacy JSON file decision

**Decision: Do NOT update legacy JSON files.**

Rationale:
- The fix script (Step 1) corrects existing Qdrant data directly
- The scanner mapping update (Step 4) ensures re-scanned legacy files get proper list splitting for both `map_` and `src_` fields
- Updating thousands of JSON files on disk is unnecessary churn with no benefit if the DB is already corrected
- New downloads will produce lists natively (Steps 2 & 3)

If a full re-scan is ever needed in the future, the scanner will handle the conversion automatically.

### Step 8: Verification

1. **Verify backups** exist and are non-empty in `/Volumes/disco1/data/evidencelab-ai/db-backups/`

2. **Run fix script dry-run** on both datasources:
   ```
   python scripts/fixes/fix_multivalue_to_list.py --data-source uneg --dry-run
   python scripts/fixes/fix_multivalue_to_list.py --data-source worldbank --dry-run
   ```

3. **Run fix script** to convert existing data:
   ```
   python scripts/fixes/fix_multivalue_to_list.py --data-source uneg
   python scripts/fixes/fix_multivalue_to_list.py --data-source worldbank
   ```

4. **Verify Qdrant** via API — sample documents should have list values:
   ```
   GET /collections/documents_uneg/points/{id}
   → map_country: ["Nepal", "India"] (not "Nepal; India")
   → src_country: ["Nepal", "India"] (not "Nepal; India")
   ```

5. **Verify facets** — query the facets endpoint, confirm individual countries with correct counts

6. **Test in browser** — load search page, expand country filter, verify:
   - Individual countries (no concatenated or pipe-separated values)
   - Counts match displayed search results
   - Filtering by a country works correctly

7. **Verify PostgreSQL** — `map_country` column should still have `"Nepal; India"` strings (not `{Nepal,India}` array literals)

## Files to create/modify

| File | Action | Description |
|---|---|---|
| `scripts/fixes/fix_multivalue_to_list.py` | **Create** | Fix script to convert existing Qdrant data |
| `pipeline/integration/.../uneg/download.py` | **Modify** | Output lists for multi-value fields |
| `pipeline/integration/.../worldbank/download.py` | **Modify** | Output lists for multi-value fields |
| `pipeline/processors/scanning/scanner_mapping.py` | **Modify** | Split src_ fields for re-scanned old data |
| `docs/admin/pipeline-configuration.md` | **Modify** | Add downloader JSON format documentation |

## Dependencies

- **PR #199** must be merged first (or cherry-picked into working branch) to prevent PostgreSQL corruption when lists flow through.

## Risks

- **Re-scanning old JSON files**: Mitigated by Step 4 — scanner mapping will split `src_` fields for legacy string values.
- **Other consumers**: Any code that reads `map_` or `src_` fields from Qdrant and expects strings will break. Need to audit `_split_multivalue`, `expand_multivalue_filter`, and any string operations on these fields. These workarounds can be simplified/removed once data is correct, but should remain backward-compatible in the interim (handle both strings and lists).
- **`abstract` field**: Currently treated as multi-value by `_split_if_multival` (not in `_SCALAR_FIELDS`). Should be added to `_SCALAR_FIELDS` since abstracts aren't genuinely multi-value — but this is out of scope for this plan.
