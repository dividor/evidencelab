import {
  CaseFilterConfig,
  caseToDraft,
  draftToPayload,
  emptyDraft,
  emptyFilterConfig,
  filterConfigFromFacets,
} from '../components/admin/testing/CaseEditor';
import type { Facets } from '../types/api';
import type { TestCase } from '../types/testing';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));

const REGION = 'Asia and the Pacific';
const YEAR_LABEL = 'Year Published';
const TITLE_LABEL = 'Document Title';

// A WFP-like config-driven filter field set (mirrors default_filter_fields).
const CONFIG: CaseFilterConfig = {
  facetFields: {
    src_evaluation_category: 'Evaluation Category',
    document_type: 'Document Type',
    region: 'Region',
    country: 'Country',
    language: 'Language',
  },
  rangeFields: { published_year: YEAR_LABEL },
  titleLabel: TITLE_LABEL,
};

const makeCase = (input: Record<string, unknown>, extra: Partial<TestCase> = {}): TestCase =>
  ({ id: 'c1', input, ...extra } as TestCase);

describe('filterConfigFromFacets', () => {
  test('splits facet, range and title fields like the search panel', () => {
    const facets: Facets = {
      facets: {},
      filter_fields: {
        title: TITLE_LABEL,
        country: 'Country',
        published_year: YEAR_LABEL,
      },
      range_fields: { published_year: { min: 2000, max: 2024 } },
    };
    expect(filterConfigFromFacets(facets)).toEqual({
      facetFields: { country: 'Country' },
      rangeFields: { published_year: YEAR_LABEL },
      titleLabel: TITLE_LABEL,
    });
  });
});

describe('caseToDraft', () => {
  test('splits config-declared fields out of the filters object', () => {
    const draft = caseToDraft(
      makeCase(
        {
          query: 'girls education',
          filters: {
            published_year_min: 2018,
            published_year_max: 2022,
            doc_titles: ['Report A'],
            src_evaluation_category: ['Centralized'],
            organization: 'WFP',
          },
          params: { rerank: true },
        },
        { tags: ['smoke'], notes: 'n' },
      ),
      CONFIG,
    );
    expect(draft.query).toBe('girls education');
    expect(draft.ranges).toEqual({ published_year: { min: '2018', max: '2022' } });
    expect(draft.docTitles).toEqual(['Report A']);
    expect(draft.facetValues).toEqual({ src_evaluation_category: ['Centralized'] });
    // Keys the config does not declare are carried through unchanged.
    expect(draft.extraFilters).toEqual({ organization: 'WFP' });
    expect(draft.extraInput).toEqual({ params: { rerank: true } });
    expect(draft.tags).toBe('smoke');
    expect(draft.notes).toBe('n');
  });

  test('splits country and region lists out of the filters object', () => {
    const draft = caseToDraft(
      makeCase({
        query: 'q',
        filters: { country: ['Kenya', 'Uganda'], region: [REGION] },
      }),
      CONFIG,
    );
    expect(draft.facetValues).toEqual({ country: ['Kenya', 'Uganda'], region: [REGION] });
    expect(draft.extraFilters).toEqual({});
    expect(draft.extraInput).toEqual({});
  });

  test('keeps every filter as an extra when the config declares no fields', () => {
    const filters = { country: ['Kenya'], doc_titles: ['Report A'] };
    const draft = caseToDraft(makeCase({ query: 'q', filters }), emptyFilterConfig());
    expect(draft.facetValues).toEqual({});
    expect(draft.docTitles).toEqual([]);
    expect(draft.extraFilters).toEqual(filters);
  });

  test('leaves extras empty when input is only a query', () => {
    const draft = caseToDraft(makeCase({ query: 'q' }), CONFIG);
    expect(draft).toMatchObject({
      query: 'q',
      docTitles: [],
      facetValues: {},
      ranges: {},
      extraFilters: {},
      extraInput: {},
    });
  });

  test('keeps a non-list filter value as an extra', () => {
    const draft = caseToDraft(
      makeCase({ query: 'q', filters: { doc_titles: 'not-a-list', country: 'Kenya' } }),
      CONFIG,
    );
    expect(draft.docTitles).toEqual([]);
    expect(draft.facetValues).toEqual({});
    expect(draft.extraFilters).toEqual({ doc_titles: 'not-a-list', country: 'Kenya' });
  });
});

describe('draftToPayload', () => {
  test('merges builder fields into filters', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      ranges: { published_year: { min: '2018', max: '2022' } },
      docTitles: ['Report A'],
    });
    expect(payload.input).toEqual({
      query: 'q',
      filters: {
        published_year_min: 2018,
        published_year_max: 2022,
        doc_titles: ['Report A'],
      },
    });
  });

  test('omits the filters key entirely when the builder is empty', () => {
    const payload = draftToPayload({ ...emptyDraft(), query: 'q' });
    expect(payload.input).toEqual({ query: 'q' });
    expect(payload.tags).toBeUndefined();
  });

  test('merges facet value lists into filters', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      facetValues: { country: ['Kenya'], region: [REGION], language: [] },
    });
    expect(payload.input).toEqual({
      query: 'q',
      filters: { country: ['Kenya'], region: [REGION] },
    });
  });

  test('merges extras with builder fields (builder wins on its keys)', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      ranges: { published_year: { min: '2020', max: '' } },
      docTitles: ['B'],
      extraFilters: { country: 'Kenya' },
      extraInput: { params: { limit: 10 } },
    });
    expect(payload.input).toEqual({
      query: 'q',
      params: { limit: 10 },
      filters: { country: 'Kenya', published_year_min: 2020, doc_titles: ['B'] },
    });
  });
});

describe('caseToDraft -> draftToPayload round-trip', () => {
  test('preserves query, filters, params, tags and notes', () => {
    const input = {
      query: 'q',
      filters: {
        published_year_max: 2022,
        doc_titles: ['A', 'B'],
        country: ['Kenya'],
        region: [REGION],
        src_evaluation_category: ['Centralized'],
        organization: 'WFP',
      },
      params: { rerank: true },
    };
    const payload = draftToPayload(
      caseToDraft(makeCase(input, { tags: ['t'], notes: 'n' }), CONFIG),
    );
    expect(payload.input).toEqual(input);
    expect(payload.tags).toEqual(['t']);
    expect(payload.notes).toBe('n');
  });

  test('preserves filters untouched when the config declares no fields', () => {
    const input = {
      query: 'q',
      filters: { country: ['Kenya'], doc_titles: ['A'] },
    };
    const payload = draftToPayload(caseToDraft(makeCase(input), emptyFilterConfig()));
    expect(payload.input).toEqual(input);
  });
});
