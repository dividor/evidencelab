import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { Facets, RangeInfo } from '../../../types/api';
import type { TestCase } from '../../../types/testing';
import { prettyJson } from './testingFormat';
import DocumentTitleSelect from './DocumentTitleSelect';
import FacetMultiSelect from './FacetMultiSelect';

/**
 * Which filters the case builder offers, derived from the data source's
 * config-driven search facets (the `/facets` response). This is the same
 * source that drives the search page's filter panel, so the eval builder
 * always mirrors the filters a user sees in regular search.
 */
export interface CaseFilterConfig {
  /** Core field -> display label, rendered as facet-value multiselects. */
  facetFields: Record<string, string>;
  /** Core field -> display label, rendered as min/max range inputs. */
  rangeFields: Record<string, string>;
  /** Label of the document-title filter field, when the config declares one. */
  titleLabel: string | null;
}

export const emptyFilterConfig = (): CaseFilterConfig => ({
  facetFields: {},
  rangeFields: {},
  titleLabel: null,
});

// Split the config's filter fields the same way the search panel does: fields
// with range info become min/max inputs, `title` becomes the document picker
// (stored as `doc_titles`), everything else a facet-value multiselect.
export const filterConfigFromFacets = (facets: Facets): CaseFilterConfig => {
  const config = emptyFilterConfig();
  Object.entries(facets.filter_fields || {}).forEach(([field, label]) => {
    if (field === 'title') {
      config.titleLabel = label;
    } else if (facets.range_fields?.[field]) {
      config.rangeFields[field] = label;
    } else {
      config.facetFields[field] = label;
    }
  });
  return config;
};

export interface RangeDraft {
  min: string; // empty = unset
  max: string; // empty = unset
}

export interface CaseDraft {
  query: string;
  docTitles: string[]; // filters.doc_titles (exact UI titles)
  facetValues: Record<string, string[]>; // core field -> selected values
  ranges: Record<string, RangeDraft>; // core field -> {field}_min/{field}_max
  // Keys the builder does not own are carried through unchanged so editing a
  // case never drops them: filter keys the config doesn't declare, and input
  // keys other than query/filters (e.g. `params` from an import or the API).
  extraFilters: Record<string, unknown>;
  extraInput: Record<string, unknown>;
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

// A filter value is pulled into the builder only when it is a clean list of
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
  docTitles: string[];
  facetValues: Record<string, string[]>;
  ranges: Record<string, RangeDraft>;
  rest: JsonObject;
}

// Split a stored `filters` object into the builder-owned fields — those the
// data source's filter config declares — and the remaining keys that stay in
// advanced JSON.
const splitFilters = (filters: unknown, config: CaseFilterConfig): SplitFilters => {
  if (!isPlainObject(filters)) {
    return { docTitles: [], facetValues: {}, ranges: {}, rest: {} };
  }
  const rest: JsonObject = { ...filters };
  const docTitles = config.titleLabel ? takeStringList(rest, 'doc_titles') : [];
  const facetValues: Record<string, string[]> = {};
  Object.keys(config.facetFields).forEach((field) => {
    const values = takeStringList(rest, field);
    if (values.length > 0) facetValues[field] = values;
  });
  const ranges: Record<string, RangeDraft> = {};
  Object.keys(config.rangeFields).forEach((field) => {
    const min = takeNumberString(rest, `${field}_min`);
    const max = takeNumberString(rest, `${field}_max`);
    if (min !== '' || max !== '') ranges[field] = { min, max };
  });
  return { docTitles, facetValues, ranges, rest };
};

/* ------------------------------------------------------------------ */
/*  Draft <-> case conversion                                         */
/* ------------------------------------------------------------------ */

export const emptyDraft = (): CaseDraft => ({
  query: '',
  docTitles: [],
  facetValues: {},
  ranges: {},
  extraFilters: {},
  extraInput: {},
  tags: '',
  notes: '',
});

export const caseToDraft = (testCase: TestCase, config: CaseFilterConfig): CaseDraft => {
  const input = (testCase.input || {}) as JsonObject;
  const { query, filters, ...restTop } = input as {
    query?: unknown;
    filters?: unknown;
    [k: string]: unknown;
  };
  const split = splitFilters(filters, config);
  return {
    query: typeof query === 'string' ? query : '',
    docTitles: split.docTitles,
    facetValues: split.facetValues,
    ranges: split.ranges,
    extraFilters: split.rest,
    extraInput: restTop,
    tags: (testCase.tags || []).join(', '),
    notes: testCase.notes || '',
  };
};

// Merge the builder-owned filter fields onto the carried-through extras.
const buildFilters = (draft: CaseDraft): JsonObject => {
  const base: JsonObject = { ...draft.extraFilters };
  if (draft.docTitles.length > 0) base.doc_titles = draft.docTitles;
  Object.entries(draft.facetValues).forEach(([field, values]) => {
    if (values.length > 0) base[field] = values;
  });
  Object.entries(draft.ranges).forEach(([field, range]) => {
    if (range.min.trim() !== '') base[`${field}_min`] = Number(range.min);
    if (range.max.trim() !== '') base[`${field}_max`] = Number(range.max);
  });
  return base;
};

export const draftToPayload = (draft: CaseDraft): CasePayload => {
  const mergedFilters = buildFilters(draft);
  const input: JsonObject = { query: draft.query, ...draft.extraInput };
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
/*  Filter field inputs                                               */
/* ------------------------------------------------------------------ */

interface RangeFieldInputProps {
  field: string;
  label: string;
  range: RangeDraft;
  bounds?: RangeInfo;
  onChange: (field: string, range: RangeDraft) => void;
}

const RangeFieldInput: React.FC<RangeFieldInputProps> = ({
  field,
  label,
  range,
  bounds,
  onChange,
}) => (
  <div className="form-group">
    <label>{label} (optional)</label>
    <div className="testing-range-inputs">
      <input
        type="number"
        aria-label={`${label} from`}
        value={range.min}
        onChange={(e) => onChange(field, { ...range, min: e.target.value })}
        placeholder={bounds ? String(bounds.min) : 'From'}
      />
      <span className="text-muted">–</span>
      <input
        type="number"
        aria-label={`${label} to`}
        value={range.max}
        onChange={(e) => onChange(field, { ...range, max: e.target.value })}
        placeholder={bounds ? String(bounds.max) : 'To'}
      />
    </div>
  </div>
);

/* ------------------------------------------------------------------ */
/*  Editor form (inputs only — assertions live on experiments)        */
/* ------------------------------------------------------------------ */

interface CaseEditorProps {
  initialCase: TestCase | null;
  dataSource: string;
  saving: boolean;
  submitLabel: string;
  onSubmit: (payload: CasePayload) => void;
  onCancel: () => void;
}

const CaseEditor: React.FC<CaseEditorProps> = ({
  initialCase,
  dataSource,
  saving,
  submitLabel,
  onSubmit,
  onCancel,
}) => {
  const [config, setConfig] = useState<CaseFilterConfig | null>(null);
  const [facetOptions, setFacetOptions] = useState<Record<string, string[]>>({});
  const [rangeBounds, setRangeBounds] = useState<Record<string, RangeInfo>>({});
  const [optionsError, setOptionsError] = useState(false);
  const [draft, setDraft] = useState<CaseDraft | null>(null);

  // Load the data source's search facets: they define which filter fields the
  // builder offers (from config.json's filter fields) and their pickable values.
  useEffect(() => {
    if (!dataSource) {
      setConfig(emptyFilterConfig());
      return undefined;
    }
    let cancelled = false;
    axios
      .get<Facets>(`${API_BASE_URL}/facets`, { params: { data_source: dataSource } })
      .then((resp) => {
        if (cancelled) return;
        const options: Record<string, string[]> = {};
        Object.entries(resp.data.facets || {}).forEach(([field, values]) => {
          options[field] = values.map((f) => f.value);
        });
        setFacetOptions(options);
        setRangeBounds(resp.data.range_fields || {});
        setConfig(filterConfigFromFacets(resp.data));
      })
      .catch(() => {
        // Facets are required to offer pickers; without them the builder still
        // works through the advanced JSON box, and says so.
        if (cancelled) return;
        setOptionsError(true);
        setConfig(emptyFilterConfig());
      });
    return () => {
      cancelled = true;
    };
  }, [dataSource]);

  // The filter split depends on the loaded config, so the draft is initialised
  // once the facets request settles.
  useEffect(() => {
    if (config === null) return;
    setDraft((d) => d ?? (initialCase ? caseToDraft(initialCase, config) : emptyDraft()));
  }, [config, initialCase]);

  if (config === null || draft === null) {
    return <div className="testing-case-editor text-muted">Loading filter options…</div>;
  }

  const update = (patch: Partial<CaseDraft>) => setDraft((d) => d && { ...d, ...patch });

  const updateFacetValues = (field: string, values: string[]) =>
    update({ facetValues: { ...draft.facetValues, [field]: values } });

  const updateRange = (field: string, range: RangeDraft) =>
    update({ ranges: { ...draft.ranges, [field]: range } });

  const handleSubmit = () => onSubmit(draftToPayload(draft));

  // Carried-through keys the builder does not own (e.g. `params` or filter
  // fields the config doesn't declare), shown read-only so nothing is hidden.
  const extras: JsonObject = { ...draft.extraInput };
  if (Object.keys(draft.extraFilters).length > 0) extras.filters = draft.extraFilters;

  return (
    <div className="testing-case-editor">
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

      {optionsError && (
        <p className="text-muted">
          Couldn&apos;t load the data source&apos;s filter fields — the case&apos;s
          existing filters are kept, but cannot be edited here.
        </p>
      )}

      {config.titleLabel && (
        <div className="form-group">
          <label>{config.titleLabel} (optional)</label>
          <DocumentTitleSelect
            dataSource={dataSource}
            value={draft.docTitles}
            onChange={(docTitles) => update({ docTitles })}
          />
          <small className="text-muted">
            Restrict the case to specific documents by their exact UI title.
          </small>
        </div>
      )}

      {Object.entries(config.facetFields).map(([field, label]) => {
        const options = facetOptions[field] || [];
        const selected = draft.facetValues[field] || [];
        if (options.length === 0 && selected.length === 0) return null;
        return (
          <div className="form-group" key={field}>
            <label>{label} (optional)</label>
            <FacetMultiSelect
              options={options}
              value={selected}
              onChange={(values) => updateFacetValues(field, values)}
              placeholder={`Type to filter ${label.toLowerCase()}…`}
            />
          </div>
        );
      })}

      {Object.entries(config.rangeFields).map(([field, label]) => (
        <RangeFieldInput
          key={field}
          field={field}
          label={label}
          range={draft.ranges[field] || { min: '', max: '' }}
          bounds={rangeBounds[field]}
          onChange={updateRange}
        />
      ))}

      {Object.keys(extras).length > 0 && (
        <div className="form-group">
          <label htmlFor="case-extra">Other filters / params (read-only)</label>
          <textarea
            id="case-extra"
            className="testing-json-textarea"
            value={prettyJson(extras)}
            readOnly
            rows={4}
          />
          <small className="text-muted">
            Set via CSV import or the API; kept unchanged when saving.
          </small>
        </div>
      )}

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
