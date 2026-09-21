import axios from 'axios';
import { withDocumentYears } from '../utils/briefExportYears';
import type { SearchResult } from '../types/api';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const result = (over: Partial<SearchResult>): SearchResult =>
  ({
    chunk_id: 'c1',
    doc_id: 'd1',
    title: 'A report',
    text: 'excerpt',
    score: 0.5,
    page_num: 3,
    headings: [],
    metadata: {},
    ...over,
  }) as SearchResult;

describe('withDocumentYears', () => {
  beforeEach(() => {
    mockedAxios.get.mockReset();
  });

  test('attaches each document year as a string and fetches every document once', async () => {
    mockedAxios.get.mockImplementation(async (url: string) => {
      if (url.endsWith('/document/d1')) return { data: { published_year: 2021 } };
      if (url.endsWith('/document/d2')) return { data: { published_year: '2019' } };
      throw new Error(`unexpected url ${url}`);
    });
    const results = [
      result({ chunk_id: 'c1', doc_id: 'd1' }),
      result({ chunk_id: 'c2', doc_id: 'd1', page_num: 9 }),
      result({ chunk_id: 'c3', doc_id: 'd2' }),
    ];

    const out = await withDocumentYears(results, 'wfp');

    expect(out.map((r) => r.year)).toEqual(['2021', '2021', '2019']);
    expect(mockedAxios.get).toHaveBeenCalledTimes(2);
    expect(mockedAxios.get).toHaveBeenCalledWith(
      expect.stringMatching(/\/document\/d1$/),
      { params: { data_source: 'wfp' } },
    );
    // The input results are left untouched.
    expect(results[0].year).toBeUndefined();
  });

  test('leaves results without a recorded year unchanged', async () => {
    mockedAxios.get.mockResolvedValue({ data: { published_year: null } });
    const out = await withDocumentYears([result({})], 'wfp');
    expect(out[0].year).toBeUndefined();
  });

  test('a failed lookup leaves that document without a year, warns, and keeps the others', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    mockedAxios.get.mockImplementation(async (url: string) => {
      if (url.endsWith('/document/d9')) throw new Error('Request failed with status code 500');
      return { data: { published_year: '2020' } };
    });
    const out = await withDocumentYears(
      [result({ chunk_id: 'c1', doc_id: 'd9' }), result({ chunk_id: 'c2', doc_id: 'd1' })],
      'wfp',
    );
    expect(out.map((r) => r.year)).toEqual([undefined, '2020']);
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/cited document d9: Request failed with status code 500/),
    );
    warn.mockRestore();
  });
});
