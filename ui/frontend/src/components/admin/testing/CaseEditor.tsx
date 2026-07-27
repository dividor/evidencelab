import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { Facets } from '../../../types/api';
import type { TestCase } from '../../../types/testing';
import { prettyJson } from './testingFormat';
import DocumentTitleSelect from './DocumentTitleSelect';
import FacetMultiSelect from './FacetMultiSelect';
import FilterHelp from './FilterHelp';

export interface CaseDraft {
  query: string;
  yearMin: string; // published_year_min (empty = unset)
  yearMax: string; // published_year_max (empty = unset)
  docTitles: string[]; // filters.doc_titles (exact UI titles)
  country: string[]; // filters.country
  region: string[]; // filters.region
  advancedJson: string; // remaining filters + params, as JSON
  tags: string; // comma separated
  notes: string;
}

export interface CasePayload {
  input: Record<string, unknown>;
  tags?: string[];
  notes?: string;
}

type JsonObject = Record<string, unknown>;

const isPlainObject = (value: unknown): value is JsonObject =>
  !!value && typeof value === 'object' && !Array.isArray(value);

// A doc_titles value is pulled into the builder only when it is a clean list of
// strings; anything else stays in the advanced JSON so it round-trips untouched.
const asStringList = (value: unknown): string[] | null => {
  if (!Array.isArray(value)) return null;
  const strings = value.filter((item): item is string => typeof item === 'string');
  return strings.length === value.length ? strings : null;
};

// Remove a numeric filter key from `obj` and return it as a string ('' if unset).
const takeNumberString = (obj: JsonObject, key: string): string => {
  const value = obj[key];
  if (typeof value === 'number' || typeof value === 'string') {
    delete obj[key];
    return String(value);
  }
  return '';
};

// Remove a string-list filter key from `obj` and return it ([] if not a clean
// list of strings — anything else is left in place for the advanced JSON box).
const takeStringList = (obj: JsonObject, key: string): string[] => {
  const list = asStringList(obj[key]);
  if (list) {
    delete obj[key];
    return list;
  }
  return [];
};

interface SplitFilters {
  yearMin: string;
  yearMax: string;
  docTitles: string[];
  country: string[];
  region: string[];
  rest: JsonObject;
}

// Split a stored `filters` object into the builder-owned fields (year range,
// doc_titles, country, region) and the remaining keys that stay in advanced JSON.
const splitFilters = (filters: unknown): SplitFilters => {
  if (!isPlainObject(filters)) {
    return { yearMin: '', yearMax: '', docTitles: [], country: [], region: [], rest: {} };
  }
  const rest: JsonObject = { ...filters };
  return {
    yearMin: takeNumberString(rest, 'published_year_min'),
    yearMax: takeNumberString(rest, 'published_year_max'),
    docTitles: takeStringList(rest, 'doc_titles'),
    country: takeStringList(rest, 'country'),
    region: takeStringList(rest, 'region'),
    rest,
  };
};

/* ------------------------------------------------------------------ */
/*  Draft <-> case conversion                                         */
/* ------------------------------------------------------------------ */

export const emptyDraft = (): CaseDraft => ({
  query: '',
  yearMin: '',
  yearMax: '',
  docTitles: [],
  country: [],
  region: [],
  advancedJson: '',
  tags: '',
  notes: '',
});

export const caseToDraft = (testCase: TestCase): CaseDraft => {
  const input = (testCase.input || {}) as JsonObject;
  const { query, filters, ...restTop } = input as {
    query?: unknown;
    filters?: unknown;
    [k: string]: unknown;
  };
  const split = splitFilters(filters);
  const advanced: JsonObject = { ...restTop };
  if (Object.keys(split.rest).length > 0) advanced.filters = split.rest;
  return {
    query: typeof query === 'string' ? query : '',
    yearMin: split.yearMin,
    yearMax: split.yearMax,
    docTitles: split.docTitles,
    country: split.country,
    region: split.region,
    advancedJson: Object.keys(advanced).length > 0 ? prettyJson(advanced) : '',
    tags: (testCase.tags || []).join(', '),
    notes: testCase.notes || '',
  };
};

const parseAdvanced = (json: string): JsonObject => {
  if (!json.trim()) return {};
  const parsed = JSON.parse(json);
  if (isPlainObject(parsed)) return parsed;
  throw new Error('Filters/params JSON must be an object');
};

// Merge the builder-owned filter fields onto any `filters` from advanced JSON.
const buildFilters = (draft: CaseDraft, advFilters: unknown): JsonObject => {
  const base: JsonObject = isPlainObject(advFilters) ? { ...advFilters } : {};
  if (draft.yearMin.trim() !== '') base.published_year_min = Number(draft.yearMin);
  if (draft.yearMax.trim() !== '') base.published_year_max = Number(draft.yearMax);
  if (draft.docTitles.length > 0) base.doc_titles = draft.docTitles;
  if (draft.country.length > 0) base.country = draft.country;
  if (draft.region.length > 0) base.region = draft.region;
  return base;
};

export const draftToPayload = (draft: CaseDraft): CasePayload => {
  const { filters: advFilters, ...advRest } = parseAdvanced(draft.advancedJson);
  const mergedFilters = buildFilters(draft, advFilters);
  const input: JsonObject = { query: draft.query, ...advRest };
  if (Object.keys(mergedFilters).length > 0) input.filters = mergedFilters;
  const tags = draft.tags
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return {
    input,
    tags: tags.length > 0 ? tags : undefined,
    notes: draft.notes.trim() || undefined,
  };
};

/* ------------------------------------------------------------------ */
/*  Editor form (inputs only — assertions live on experiments)        */
/* ------------------------------------------------------------------ */

interface CaseEditorProps {
  initial: CaseDraft;
  dataSource: string;
  saving: boolean;
  submitLabel: string;
  onSubmit: (payload: CasePayload) => void;
  onCancel: () => void;
}

const CaseEditor: React.FC<CaseEditorProps> = ({
  initial,
  dataSource,
  saving,
  submitLabel,
  onSubmit,
  onCancel,
}) => {
  const [draft, setDraft] = useState<CaseDraft>(initial);
  const [localError, setLocalError] = useState('');
  const [countryOptions, setCountryOptions] = useState<string[]>([]);
  const [regionOptions, setRegionOptions] = useState<string[]>([]);

  // Load the data source's country/region facet values so those filters can be
  // picked from real options instead of hand-written JSON.
  useEffect(() => {
    if (!dataSource) return undefined;
    let cancelled = false;
    axios
      .get<Facets>(`${API_BASE_URL}/facets`, { params: { data_source: dataSource } })
      .then((resp) => {
        if (cancelled) return;
        const facets = resp.data.facets || {};
        setCountryOptions((facets.country || []).map((f) => f.value));
        setRegionOptions((facets.region || []).map((f) => f.value));
      })
      .catch(() => {
        // Non-fatal: the pickers simply offer no options if facets can't load.
      });
    return () => {
      cancelled = true;
    };
  }, [dataSource]);

  const update = (patch: Partial<CaseDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const handleSubmit = () => {
    setLocalError('');
    try {
      onSubmit(draftToPayload(draft));
    } catch (err: any) {
      setLocalError(err.message || 'Invalid JSON in filters/params');
    }
  };

  return (
    <div className="testing-case-editor">
      {localError && <div className="auth-error">{localError}</div>}

      <div className="form-group">
        <label htmlFor="case-query">Query</label>
        <input
          id="case-query"
          type="text"
          value={draft.query}
          onChange={(e) => update({ query: e.target.value })}
          placeholder="Search query / question"
        />
      </div>

      <div className="form-group">
        <label>Documents (optional)</label>
        <DocumentTitleSelect
          dataSource={dataSource}
          value={draft.docTitles}
          onChange={(docTitles) => update({ docTitles })}
        />
        <small className="text-muted">
          Restrict the case to specific documents by their exact UI title.
        </small>
      </div>

      {(countryOptions.length > 0 || draft.country.length > 0) && (
        <div className="form-group">
          <label>Country (optional)</label>
          <FacetMultiSelect
            options={countryOptions}
            value={draft.country}
            onChange={(country) => update({ country })}
            placeholder="Type to filter countries…"
          />
        </div>
      )}

      {(regionOptions.length > 0 || draft.region.length > 0) && (
        <div className="form-group">
          <label>Region (optional)</label>
          <FacetMultiSelect
            options={regionOptions}
            value={draft.region}
            onChange={(region) => update({ region })}
            placeholder="Type to filter regions…"
          />
        </div>
      )}

      <div className="form-group">
        <label>Publication year (optional)</label>
        <div className="testing-year-range">
          <input
            type="number"
            aria-label="Published year from"
            value={draft.yearMin}
            onChange={(e) => update({ yearMin: e.target.value })}
            placeholder="From"
          />
          <span className="text-muted">–</span>
          <input
            type="number"
            aria-label="Published year to"
            value={draft.yearMax}
            onChange={(e) => update({ yearMax: e.target.value })}
            placeholder="To"
          />
        </div>
      </div>

      <details className="form-group testing-advanced-filters">
        <summary className="testing-raw-toggle">Advanced filters / params (JSON)</summary>
        <textarea
          id="case-extra"
          className="testing-json-textarea"
          value={draft.advancedJson}
          onChange={(e) => update({ advancedJson: e.target.value })}
          placeholder={'{\n  "filters": { "country": "Kenya" },\n  "params": {}\n}'}
          rows={5}
        />
        <FilterHelp />
      </details>

      <div className="form-group">
        <label htmlFor="case-tags">Tags (comma separated)</label>
        <input
          id="case-tags"
          type="text"
          value={draft.tags}
          onChange={(e) => update({ tags: e.target.value })}
          placeholder="regression, smoke"
        />
      </div>

      <div className="form-group">
        <label htmlFor="case-notes">Notes</label>
        <textarea
          id="case-notes"
          className="testing-json-textarea"
          value={draft.notes}
          onChange={(e) => update({ notes: e.target.value })}
          rows={2}
        />
      </div>

      <div className="testing-case-editor-actions">
        <button type="button" className="btn-sm btn-cancel" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-sm btn-primary"
          onClick={handleSubmit}
          disabled={saving}
        >
          {saving ? 'Saving...' : submitLabel}
        </button>
      </div>
    </div>
  );
};

export default CaseEditor;
