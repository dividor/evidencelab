import {
  getSearchStateFromURL,
  mergeGroupSettings,
  SYSTEM_DEFAULTS,
  DEFAULT_SECTION_TYPES,
} from '../utils/searchUrl';
import type { SearchSettings } from '../types/auth';

describe('mergeGroupSettings', () => {
  test('returns empty object for empty group list', () => {
    const result = mergeGroupSettings([]);
    expect(result).toEqual({});
  });

  test('returns empty object when group has no settings', () => {
    const result = mergeGroupSettings([{ search_settings: null }]);
    expect(result).toEqual({});
  });

  test('returns settings from single group', () => {
    const result = mergeGroupSettings([
      { search_settings: { denseWeight: 0.5, rerank: false } },
    ]);
    expect(result).toEqual({ denseWeight: 0.5, rerank: false });
  });

  test('first non-null value wins across multiple groups', () => {
    const result = mergeGroupSettings([
      { search_settings: { denseWeight: 0.3 } },
      { search_settings: { denseWeight: 0.8, rerank: false } },
    ]);
    expect(result).toEqual({ denseWeight: 0.3, rerank: false });
  });

  test('skips groups with null settings', () => {
    const result = mergeGroupSettings([
      { search_settings: null },
      { search_settings: { rerank: true } },
    ]);
    expect(result).toEqual({ rerank: true });
  });

  test('skips groups with undefined settings', () => {
    const result = mergeGroupSettings([
      { search_settings: undefined },
      { search_settings: { deduplicate: false } },
    ]);
    expect(result).toEqual({ deduplicate: false });
  });
});

describe('SYSTEM_DEFAULTS', () => {
  test('contains all expected keys with correct defaults', () => {
    expect(SYSTEM_DEFAULTS.denseWeight).toBe(0.8);
    expect(SYSTEM_DEFAULTS.rerank).toBe(true);
    expect(SYSTEM_DEFAULTS.recencyBoost).toBe(false);
    expect(SYSTEM_DEFAULTS.recencyWeight).toBe(0.15);
    expect(SYSTEM_DEFAULTS.recencyScaleDays).toBe(365);
    expect(SYSTEM_DEFAULTS.keywordBoostShortQueries).toBe(true);
    expect(SYSTEM_DEFAULTS.minChunkSize).toBe(100);
    expect(SYSTEM_DEFAULTS.semanticHighlighting).toBe(true);
    expect(SYSTEM_DEFAULTS.autoMinScore).toBe(false);
    expect(SYSTEM_DEFAULTS.deduplicate).toBe(true);
    expect(SYSTEM_DEFAULTS.fieldBoost).toBe(true);
  });
});

describe('getSearchStateFromURL with groupDefaults', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
    });
  });

  const setURL = (search: string) => {
    Object.defineProperty(window, 'location', {
      value: { ...originalLocation, search },
      writable: true,
    });
  };

  test('uses system defaults when no group defaults provided', () => {
    setURL('?q=test');
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES);
    expect(state.denseWeight).toBe(0.8);
    expect(state.rerank).toBe(true);
    expect(state.deduplicate).toBe(true);
  });

  test('group defaults override system defaults', () => {
    setURL('?q=test');
    const groupDefaults: SearchSettings = { denseWeight: 0.5, rerank: false };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    expect(state.denseWeight).toBe(0.5);
    expect(state.rerank).toBe(false);
    // Other settings remain at system defaults
    expect(state.deduplicate).toBe(true);
  });

  test('URL param overrides group default', () => {
    setURL('?q=test&weight=0.3&rerank=true');
    const groupDefaults: SearchSettings = { denseWeight: 0.5, rerank: false };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    // URL params win over group defaults
    expect(state.denseWeight).toBe(0.3);
    expect(state.rerank).toBe(true);
  });

  test('group defaults for boolean settings', () => {
    setURL('?q=test');
    const groupDefaults: SearchSettings = {
      semanticHighlighting: false,
      autoMinScore: true,
      deduplicate: false,
    };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    expect(state.semanticHighlighting).toBe(false);
    expect(state.autoMinScore).toBe(true);
    expect(state.deduplicate).toBe(false);
  });

  test('group defaults for integer settings', () => {
    setURL('?q=test');
    const groupDefaults: SearchSettings = {
      minChunkSize: 200,
      recencyScaleDays: 180,
    };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    expect(state.minChunkSize).toBe(200);
    expect(state.recencyScaleDays).toBe(180);
  });

  test('group defaults for section types', () => {
    setURL('?q=test');
    const groupDefaults: SearchSettings = {
      sectionTypes: ['findings', 'conclusions'],
    };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    expect(state.sectionTypes).toEqual(['findings', 'conclusions']);
  });

  test('URL sections param overrides group section types', () => {
    setURL('?q=test&sections=methodology,other');
    const groupDefaults: SearchSettings = {
      sectionTypes: ['findings', 'conclusions'],
    };
    const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
    expect(state.sectionTypes).toEqual(['methodology', 'other']);
  });
});
