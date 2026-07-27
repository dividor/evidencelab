import {
  caseToDraft,
  draftToPayload,
  emptyDraft,
} from '../components/admin/testing/CaseEditor';
import type { TestCase } from '../types/testing';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));

const REGION = 'Asia and the Pacific';

const makeCase = (input: Record<string, unknown>, extra: Partial<TestCase> = {}): TestCase =>
  ({ id: 'c1', input, ...extra } as TestCase);

describe('caseToDraft', () => {
  test('splits year range and doc_titles out of the filters object', () => {
    const draft = caseToDraft(
      makeCase(
        {
          query: 'girls education',
          filters: {
            published_year_min: 2018,
            published_year_max: 2022,
            doc_titles: ['Report A'],
            country: 'Kenya',
          },
          params: { rerank: true },
        },
        { tags: ['smoke'], notes: 'n' },
      ),
    );
    expect(draft.query).toBe('girls education');
    expect(draft.yearMin).toBe('2018');
    expect(draft.yearMax).toBe('2022');
    expect(draft.docTitles).toEqual(['Report A']);
    // Remaining filter keys + params round-trip through the advanced JSON box.
    expect(JSON.parse(draft.advancedJson)).toEqual({
      filters: { country: 'Kenya' },
      params: { rerank: true },
    });
    expect(draft.tags).toBe('smoke');
    expect(draft.notes).toBe('n');
  });

  test('splits country and region lists out of the filters object', () => {
    const draft = caseToDraft(
      makeCase({
        query: 'q',
        filters: { country: ['Kenya', 'Uganda'], region: [REGION] },
      }),
    );
    expect(draft.country).toEqual(['Kenya', 'Uganda']);
    expect(draft.region).toEqual([REGION]);
    expect(draft.advancedJson).toBe('');
  });

  test('leaves advanced JSON empty when input is only a query', () => {
    const draft = caseToDraft(makeCase({ query: 'q' }));
    expect(draft).toMatchObject({
      query: 'q',
      yearMin: '',
      yearMax: '',
      docTitles: [],
      advancedJson: '',
    });
  });

  test('keeps a non-list doc_titles value in advanced JSON', () => {
    const draft = caseToDraft(makeCase({ query: 'q', filters: { doc_titles: 'not-a-list' } }));
    expect(draft.docTitles).toEqual([]);
    expect(JSON.parse(draft.advancedJson)).toEqual({ filters: { doc_titles: 'not-a-list' } });
  });
});

describe('draftToPayload', () => {
  test('merges builder fields into filters', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      yearMin: '2018',
      yearMax: '2022',
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

  test('merges country and region lists into filters', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      country: ['Kenya'],
      region: [REGION],
    });
    expect(payload.input).toEqual({
      query: 'q',
      filters: { country: ['Kenya'], region: [REGION] },
    });
  });

  test('merges advanced filters with builder fields (builder wins on year/docs)', () => {
    const payload = draftToPayload({
      ...emptyDraft(),
      query: 'q',
      yearMin: '2020',
      docTitles: ['B'],
      advancedJson: JSON.stringify({ filters: { country: 'Kenya' }, params: { limit: 10 } }),
    });
    expect(payload.input).toEqual({
      query: 'q',
      params: { limit: 10 },
      filters: { country: 'Kenya', published_year_min: 2020, doc_titles: ['B'] },
    });
  });

  test('throws when advanced JSON is not an object', () => {
    expect(() =>
      draftToPayload({ ...emptyDraft(), query: 'q', advancedJson: '[1, 2]' }),
    ).toThrow(/must be an object/);
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
      },
      params: { rerank: true },
    };
    const payload = draftToPayload(
      caseToDraft(makeCase(input, { tags: ['t'], notes: 'n' })),
    );
    expect(payload.input).toEqual(input);
    expect(payload.tags).toEqual(['t']);
    expect(payload.notes).toBe('n');
  });
});
