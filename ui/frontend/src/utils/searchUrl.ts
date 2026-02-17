import { SearchFilters } from '../types/api';

export interface SearchStateFromURL {
  query: string;
  filters: SearchFilters;
  selectedFilters: Record<string, string[]>;
  denseWeight: number;
  rerank: boolean;
  recencyBoost: boolean;
  recencyWeight: number;
  recencyScaleDays: number;
  sectionTypes: string[];
  keywordBoostShortQueries: boolean;
  minChunkSize: number;
  semanticHighlighting: boolean;
  autoMinScore: boolean;
  deduplicate: boolean;
  fieldBoost: boolean;
  fieldBoostFields: Record<string, number>;
  model: string | null;
  modelCombo: string | null;
  dataset: string | null;
}

export const DEFAULT_FIELD_BOOST_FIELDS: Record<string, number> = { country: 0.5, organization: 0.5 };

export const DEFAULT_SECTION_TYPES = [
  'executive_summary',
  'context',
  'methodology',
  'findings',
  'conclusions',
  'recommendations',
  'other',
];

const parseFilterParam = (params: URLSearchParams, key: string): string[] => {
  const value = params.get(key);
  if (!value) return [];
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
};

const parseFloatParam = (
  params: URLSearchParams,
  key: string,
  defaultValue: number
): number => {
  const value = params.get(key);
  return value === null ? defaultValue : parseFloat(value);
};

const parseIntParam = (
  params: URLSearchParams,
  key: string,
  defaultValue: number
): number => {
  const value = params.get(key);
  return value === null ? defaultValue : parseInt(value, 10);
};

const parseBooleanParam = (
  params: URLSearchParams,
  key: string,
  defaultValue: boolean
): boolean => {
  const value = params.get(key);
  return value === null ? defaultValue : value === 'true';
};

const parseSectionTypes = (
  params: URLSearchParams,
  defaultSectionTypes: string[]
): string[] => {
  const sectionTypesParam = params.get('sections');
  return sectionTypesParam && sectionTypesParam.trim()
    ? sectionTypesParam.split(',').filter((item) => item.trim())
    : defaultSectionTypes;
};

const parseFilters = (
  params: URLSearchParams,
  coreFields: string[]
): {
  filters: SearchFilters;
  selectedFilters: Record<string, string[]>;
} => {
  const filters: SearchFilters = {};
  const selectedFilters: Record<string, string[]> = {};

  for (const field of coreFields) {
    const value = params.get(field);
    if (value) {
      filters[field] = value;
      selectedFilters[field] = parseFilterParam(params, field);
    } else {
      selectedFilters[field] = [];
    }
  }

  return { filters, selectedFilters };
};

const parseFieldBoostFields = (params: URLSearchParams): Record<string, number> => {
  const raw = params.get('field_boost_fields');
  if (!raw) return { ...DEFAULT_FIELD_BOOST_FIELDS };
  const result: Record<string, number> = {};
  for (const item of raw.split(',')) {
    const trimmed = item.trim();
    if (!trimmed) continue;
    const colonIdx = trimmed.indexOf(':');
    if (colonIdx > 0) {
      const field = trimmed.slice(0, colonIdx);
      const weight = parseFloat(trimmed.slice(colonIdx + 1));
      result[field] = isNaN(weight) ? 0.5 : weight;
    } else {
      result[trimmed] = 0.5;
    }
  }
  return Object.keys(result).length > 0 ? result : { ...DEFAULT_FIELD_BOOST_FIELDS };
};

export const getSearchStateFromURL = (
  coreFields: string[],
  defaultSectionTypes: string[]
): SearchStateFromURL => {
  const params = new URLSearchParams(window.location.search);
  const { filters, selectedFilters } = parseFilters(params, coreFields);

  return {
    query: params.get('q') || '',
    filters,
    selectedFilters,
    denseWeight: parseFloatParam(params, 'weight', 0.8),
    rerank: parseBooleanParam(params, 'rerank', true),
    recencyBoost: parseBooleanParam(params, 'recency', false),
    recencyWeight: parseFloatParam(params, 'recency_weight', 0.15),
    recencyScaleDays: parseIntParam(params, 'recency_scale', 365),
    sectionTypes: parseSectionTypes(params, defaultSectionTypes),
    keywordBoostShortQueries: parseBooleanParam(params, 'keyword_boost', true),
    minChunkSize: parseIntParam(params, 'min_chunk_size', 100),
    semanticHighlighting: parseBooleanParam(params, 'highlight', true),
    autoMinScore: parseBooleanParam(params, 'auto_min_score', false),
    deduplicate: parseBooleanParam(params, 'deduplicate', true),
    fieldBoost: parseBooleanParam(params, 'field_boost', true),
    fieldBoostFields: parseFieldBoostFields(params),
    model: params.get('model'),
    modelCombo: params.get('model_combo'),
    dataset: params.get('dataset'),
  };
};

const setParamIfNonEmpty = (
  params: URLSearchParams,
  key: string,
  value?: string | null
): void => {
  if (value) {
    params.set(key, value);
  }
};

const setParamIfDefined = (
  params: URLSearchParams,
  key: string,
  value?: string | number | boolean | null
): void => {
  if (value !== undefined && value !== null) {
    params.set(key, value.toString());
  }
};

const setParamIfNotDefault = (
  params: URLSearchParams,
  key: string,
  value: number | undefined,
  defaultValue: number
): void => {
  if (value !== undefined && value !== defaultValue) {
    params.set(key, value.toString());
  }
};

const setParamIfFalse = (
  params: URLSearchParams,
  key: string,
  value?: boolean
): void => {
  if (value === false) {
    params.set(key, 'false');
  }
};

const setParamIfTrue = (
  params: URLSearchParams,
  key: string,
  value?: boolean
): void => {
  if (value) {
    params.set(key, 'true');
  }
};

const setFilterParams = (params: URLSearchParams, filters: SearchFilters): void => {
  for (const [field, value] of Object.entries(filters)) {
    if (value) {
      params.set(field, value);
    }
  }
};

export const buildSearchURL = (
  query: string,
  filters: SearchFilters,
  denseWeight?: number,
  rerank?: boolean,
  recencyBoost?: boolean,
  recencyWeight?: number,
  recencyScaleDays?: number,
  sectionTypes?: string[],
  keywordBoostShortQueries?: boolean,
  minChunkSize?: number,
  semanticHighlighting?: boolean,
  autoMinScore?: boolean,
  deduplicate?: boolean,
  model?: string | null,
  modelCombo?: string | null,
  dataset?: string | null,
  fieldBoost?: boolean,
  fieldBoostFields?: Record<string, number>
): string => {
  const params = new URLSearchParams();
  setParamIfNonEmpty(params, 'q', query);
  setFilterParams(params, filters);
  setParamIfNotDefault(params, 'weight', denseWeight, 0.8);
  setParamIfDefined(params, 'rerank', rerank);
  setParamIfTrue(params, 'recency', recencyBoost);
  setParamIfNotDefault(params, 'recency_weight', recencyWeight, 0.15);
  setParamIfNotDefault(params, 'recency_scale', recencyScaleDays, 365);
  if (sectionTypes && sectionTypes.length > 0) {
    params.set('sections', sectionTypes.join(','));
  }
  setParamIfFalse(params, 'keyword_boost', keywordBoostShortQueries);
  setParamIfNotDefault(params, 'min_chunk_size', minChunkSize, 100);
  setParamIfFalse(params, 'highlight', semanticHighlighting);
  setParamIfTrue(params, 'auto_min_score', autoMinScore);
  setParamIfFalse(params, 'deduplicate', deduplicate);
  setParamIfFalse(params, 'field_boost', fieldBoost);
  if (fieldBoostFields && Object.keys(fieldBoostFields).length > 0) {
    const encoded = Object.entries(fieldBoostFields)
      .map(([field, weight]) => `${field}:${weight}`)
      .join(',');
    params.set('field_boost_fields', encoded);
  }
  setParamIfNonEmpty(params, 'model', model);
  setParamIfNonEmpty(params, 'model_combo', modelCombo);
  setParamIfNonEmpty(params, 'dataset', dataset);
  return params.toString();
};
