/**
 * Unit tests for facetMerge — the helpers that combine the unfiltered
 * "all values" facet list with per-result counts in the search sidebar.
 *
 * The regression these guard against:
 *   The backend's /facets endpoint normalises language values from ISO
 *   codes (`en`) into full names (`English`) before returning them. The
 *   per-result side reads the raw `sys_language` from each chunk, which
 *   stays in code form. Without normalising the per-result side too,
 *   the merge treated `en` and `English` as different values and the
 *   sidebar showed both — `en` with the real count and `English` with
 *   no count next to it.
 */
import {
  countFieldValues,
  extractFieldValues,
  mergeFacetField,
  orderFacetValuesForDisplay,
  resolveMetaKey,
} from '../facetMerge';
import type { FacetValue, SearchResult } from '../../types/api';

const makeDoc = (overrides: Partial<SearchResult> = {}): SearchResult =>
  ({
    chunk_id: 'c1',
    doc_id: 'd1',
    text: '',
    page_num: 1,
    headings: [],
    score: 0,
    title: 'Doc',
    metadata: {},
    ...overrides,
  } as SearchResult);

describe('resolveMetaKey', () => {
  test('language alias maps to sys_language', () => {
    expect(resolveMetaKey('language')).toBe('sys_language');
  });
  test('prefixed fields are returned verbatim', () => {
    expect(resolveMetaKey('map_country')).toBe('map_country');
    expect(resolveMetaKey('src_doc_year')).toBe('src_doc_year');
    expect(resolveMetaKey('tag_climate')).toBe('tag_climate');
  });
  test('unprefixed fields get the map_ prefix', () => {
    expect(resolveMetaKey('country')).toBe('map_country');
    expect(resolveMetaKey('organization')).toBe('map_organization');
  });
});

describe('extractFieldValues', () => {
  test('reads from metadata first, then top-level', () => {
    expect(extractFieldValues(makeDoc({ metadata: { foo: 'A' } }), 'foo')).toEqual(['A']);
    expect(
      extractFieldValues(makeDoc({ metadata: {}, ...{ foo: 'B' } } as SearchResult), 'foo'),
    ).toEqual(['B']);
  });
  test('returns [] for missing values', () => {
    expect(extractFieldValues(makeDoc({ metadata: {} }), 'missing')).toEqual([]);
  });
  test('splits semicolon and pipe-separated strings', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { tag: 'A; B; C' } }), 'tag'),
    ).toEqual(['A', 'B', 'C']);
    expect(
      extractFieldValues(makeDoc({ metadata: { tag: 'A | B' } }), 'tag'),
    ).toEqual(['A', 'B']);
  });
  test('preserves array values as-is', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { tag: ['X', 'Y'] } }), 'tag'),
    ).toEqual(['X', 'Y']);
  });
  test('language: maps ISO code to full name (sys_language)', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { sys_language: 'en' } }), 'sys_language'),
    ).toEqual(['English']);
    expect(
      extractFieldValues(makeDoc({ metadata: { sys_language: 'fr' } }), 'sys_language'),
    ).toEqual(['French']);
  });
  test('language: maps ISO code to full name (language alias)', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { language: 'es' } }), 'language'),
    ).toEqual(['Spanish']);
  });
  test('language: handles uppercase codes', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { sys_language: 'EN' } }), 'sys_language'),
    ).toEqual(['English']);
  });
  test('language: passes through unknown codes / already-full names', () => {
    expect(
      extractFieldValues(makeDoc({ metadata: { sys_language: 'English' } }), 'sys_language'),
    ).toEqual(['English']);
    expect(
      extractFieldValues(makeDoc({ metadata: { sys_language: 'xx' } }), 'sys_language'),
    ).toEqual(['xx']);
  });
  test('non-language fields are NOT touched by the language map', () => {
    // 'en' must not become 'English' on a country field, even by accident.
    expect(
      extractFieldValues(makeDoc({ metadata: { map_country: 'en' } }), 'map_country'),
    ).toEqual(['en']);
  });
});

describe('countFieldValues', () => {
  test('language: codes are normalised before counting (no duplicate buckets)', () => {
    const docs = [
      makeDoc({ metadata: { sys_language: 'en' } }),
      makeDoc({ metadata: { sys_language: 'EN' } }),
      makeDoc({ metadata: { sys_language: 'English' } }),
      makeDoc({ metadata: { sys_language: 'fr' } }),
    ];
    const counts = countFieldValues(docs, 'sys_language');
    expect(counts.get('English')).toBe(3);
    expect(counts.get('French')).toBe(1);
    expect(counts.has('en')).toBe(false);
  });
  test('counts a multi-valued field once per occurrence', () => {
    const docs = [
      makeDoc({ metadata: { tag: ['A', 'B'] } }),
      makeDoc({ metadata: { tag: 'A; C' } }),
    ];
    const counts = countFieldValues(docs, 'tag');
    expect(counts.get('A')).toBe(2);
    expect(counts.get('B')).toBe(1);
    expect(counts.get('C')).toBe(1);
  });
});

describe('mergeFacetField', () => {
  test('regression: language code en collapses onto English bucket', () => {
    // Real-world shape that triggered the bug:
    //   allValues from /facets contains the *full names* (English, …).
    //   resultCounts derived from chunk metadata used to contain *codes*.
    // After the fix, resultCounts contains full names too, so the merge
    // updates the English entry's count and never appends a stray "en".
    const allValues: FacetValue[] = [
      { value: 'English', count: 264 },
      { value: 'French', count: 39 },
      { value: 'Spanish', count: 32 },
    ];
    const docs = [
      makeDoc({ metadata: { sys_language: 'en' } }),
      makeDoc({ metadata: { sys_language: 'en' } }),
      makeDoc({ metadata: { sys_language: 'fr' } }),
    ];
    const resultCounts = countFieldValues(docs, 'sys_language');
    const merged = mergeFacetField(allValues, resultCounts);
    expect(merged.map((m) => m.value)).toEqual(['English', 'French', 'Spanish']);
    expect(merged.find((m) => m.value === 'English')!.count).toBe(2);
    expect(merged.find((m) => m.value === 'French')!.count).toBe(1);
    expect(merged.find((m) => m.value === 'Spanish')!.count).toBe(0);
    expect(merged.some((m) => m.value === 'en' || m.value === 'fr')).toBe(false);
  });
  test('preserves all-DB values that have no per-result count', () => {
    const allValues: FacetValue[] = [
      { value: 'A', count: 100 },
      { value: 'B', count: 50 },
    ];
    const merged = mergeFacetField(allValues, new Map([['A', 3]]));
    expect(merged).toEqual([
      { value: 'A', count: 3 },
      { value: 'B', count: 0 },
    ]);
  });
  test('appends result-only values not in the all-DB list', () => {
    const allValues: FacetValue[] = [{ value: 'A', count: 10 }];
    const merged = mergeFacetField(
      allValues,
      new Map([
        ['A', 2],
        ['NEW', 5],
      ]),
    );
    expect(merged).toEqual([
      { value: 'NEW', count: 5 },
      { value: 'A', count: 2 },
    ]);
  });
  test('non-zero counts sort before zero-count entries', () => {
    const merged = mergeFacetField(
      [
        { value: 'Zero', count: 100 },
        { value: 'Hit', count: 50 },
      ],
      new Map([['Hit', 7]]),
    );
    expect(merged.map((m) => m.value)).toEqual(['Hit', 'Zero']);
  });
});

describe('orderFacetValuesForDisplay', () => {
  test('country values when count-ordered then alphabetised by value', () => {
    const values: FacetValue[] = [
      { value: 'Zimbabwe', count: 90 },
      { value: 'Afghanistan', count: 50 },
      { value: 'Kenya', count: 70 },
    ];
    const ordered = orderFacetValuesForDisplay('country', values);
    expect(ordered.map((v) => v.value)).toEqual(['Afghanistan', 'Kenya', 'Zimbabwe']);
  });

  test('country alphabetising preserves each value count', () => {
    const values: FacetValue[] = [
      { value: 'Kenya', count: 70 },
      { value: 'Afghanistan', count: 50 },
    ];
    const ordered = orderFacetValuesForDisplay('country', values);
    expect(ordered).toEqual([
      { value: 'Afghanistan', count: 50 },
      { value: 'Kenya', count: 70 },
    ]);
  });

  test('non-country field when called then order unchanged', () => {
    const values: FacetValue[] = [
      { value: 'Report', count: 90 },
      { value: 'Evaluation', count: 50 },
    ];
    const ordered = orderFacetValuesForDisplay('document_type', values);
    expect(ordered.map((v) => v.value)).toEqual(['Report', 'Evaluation']);
  });

  test('country sorting when given input then does not mutate it', () => {
    const values: FacetValue[] = [
      { value: 'Zimbabwe', count: 90 },
      { value: 'Afghanistan', count: 50 },
    ];
    orderFacetValuesForDisplay('country', values);
    expect(values.map((v) => v.value)).toEqual(['Zimbabwe', 'Afghanistan']);
  });
});
