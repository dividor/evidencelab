/**
 * Facet merging utilities for the Search tab sidebar.
 *
 * The /facets endpoint returns two views of the data:
 *   - The full-dataset view (no query) — used as the canonical list of
 *     possible filter values per field (`allFacets`).
 *   - The per-query view — counts narrowed to the current search.
 *
 * The displayed sidebar merges these two so the user always sees the
 * full list of available values, with counts reflecting the current
 * results. These helpers do that merging.
 *
 * Language is the one field where the backend rewrites raw values
 * (`en`, `fr`) into full names (`English`, `French`) before returning
 * them — to match, this module normalises the per-result side too,
 * otherwise we'd display both forms and the merge would treat them as
 * separate values (the bug fixed here).
 */
import { FacetValue, SearchResult } from '../types/api';
import { LANGUAGES } from '../constants';

/** Resolve the metadata key on a result document for a given facet field. */
export const resolveMetaKey = (field: string): string => {
  if (field === 'language') return 'sys_language';
  if (field.startsWith('map_') || field.startsWith('src_') || field.startsWith('tag_')) {
    return field;
  }
  return `map_${field}`;
};

const isLanguageMetaKey = (metaKey: string): boolean =>
  metaKey === 'sys_language' || metaKey === 'language';

/** Extract and normalise a metadata value into individual strings.
 *
 *  Splits semicolon- or pipe-separated values into a list, then for the
 *  language field maps ISO codes (`en`) to full names (`English`) so they
 *  align with what the backend returned in the all-DB facet list.
 *  Anything we don't recognise passes through untouched. */
export const extractFieldValues = (doc: SearchResult, metaKey: string): string[] => {
  const val = doc.metadata?.[metaKey] ?? (doc as Record<string, unknown>)[metaKey];
  if (!val) return [];
  const raw = Array.isArray(val)
    ? val
    : typeof val === 'string' && val.includes('; ')
      ? val.split('; ')
      : typeof val === 'string' && val.includes(' | ')
        ? val.split(' | ')
        : [val];
  const trimmed = raw.map((v) => String(v).trim()).filter(Boolean);
  if (isLanguageMetaKey(metaKey)) {
    return trimmed.map((v) => LANGUAGES[v.toLowerCase()] || v);
  }
  return trimmed;
};

/** Count per-field values across deduplicated docs. */
export const countFieldValues = (
  docs: SearchResult[],
  metaKey: string,
): Map<string, number> => {
  const counts = new Map<string, number>();
  for (const doc of docs) {
    for (const v of extractFieldValues(doc, metaKey)) {
      counts.set(v, (counts.get(v) || 0) + 1);
    }
  }
  return counts;
};

/** Merge all-DB facet values with result-derived counts.
 *
 *  All values from the full-dataset facets are preserved; their counts
 *  are overwritten with the per-result tally (0 if absent). Any values
 *  appearing in the results that aren't in the all-DB list get appended
 *  — this should be rare in practice but keeps the count visible if it
 *  happens. Sorts non-zero counts first, then by descending count, then
 *  alphabetically. */
export const mergeFacetField = (
  allValues: FacetValue[],
  resultCounts: Map<string, number>,
): FacetValue[] => {
  const seen = new Set<string>();
  const merged: FacetValue[] = allValues.map((v) => {
    seen.add(v.value);
    return { ...v, count: resultCounts.get(v.value) ?? 0 };
  });
  for (const [val, count] of resultCounts) {
    if (!seen.has(val)) merged.push({ value: val, count });
  }
  merged.sort((a, b) => {
    if (a.count > 0 && b.count === 0) return -1;
    if (a.count === 0 && b.count > 0) return 1;
    if (a.count !== b.count) return b.count - a.count;
    return a.value.localeCompare(b.value);
  });
  return merged;
};

/** Core facet fields whose filter values are always displayed in
 *  alphabetical order rather than by count. Country lists are long and
 *  count order makes them hard to scan or to spot near-duplicate names,
 *  so we sort A→Z instead. */
const ALPHABETICAL_FACET_FIELDS = new Set(['country']);

/** Order facet values for display.
 *
 *  For fields in {@link ALPHABETICAL_FACET_FIELDS} (currently `country`),
 *  returns a new array sorted alphabetically by display value. All other
 *  fields are returned unchanged, preserving the upstream (count-based)
 *  order. Used as the final display gate so both the Search sidebar and
 *  the Heatmapper filter modal — which share this code path — show
 *  country filters alphabetically. */
export const orderFacetValuesForDisplay = (
  coreField: string,
  values: FacetValue[],
): FacetValue[] =>
  ALPHABETICAL_FACET_FIELDS.has(coreField)
    ? [...values].sort((a, b) => a.value.localeCompare(b.value))
    : values;
