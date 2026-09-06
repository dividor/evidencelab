import { documentYear, groupRelevance, groupResultsByDocument, sortDocumentGroups } from '../utils/resultGrouping';
import type { SearchResult } from '../types/api';

const result = (chunkId: string, docId: string, score: number, year?: string): SearchResult => ({
  chunk_id: chunkId, doc_id: docId, text: 't', page_num: 1, headings: [], score, title: `Doc ${docId}`, metadata: {}, year,
});

describe('groupResultsByDocument', () => {
  test('groups by document in order of first appearance, keeping ranked order inside', () => {
    const groups = groupResultsByDocument([
      result('b1', 'B', 0.9), result('a1', 'A', 0.8), result('b2', 'B', 0.7), result('a2', 'A', 0.6), result('c1', 'C', 0.5),
    ]);
    expect(groups.map((g) => g.docId)).toEqual(['B', 'A', 'C']);
    expect(groups[0].results.map((r) => r.chunk_id)).toEqual(['b1', 'b2']);
    expect(groups[1].results.map((r) => r.chunk_id)).toEqual(['a1', 'a2']);
    expect(groups[2].results).toHaveLength(1);
  });

  test('returns no groups for no results', () => {
    expect(groupResultsByDocument([])).toEqual([]);
  });
});

describe('sortDocumentGroups', () => {
  const groups = () =>
    groupResultsByDocument([
      result('a1', 'A', 0.9, '2019'), result('b1', 'B', 0.5, '2024'), result('b2', 'B', 0.5, '2024'),
      result('c1', 'C', 0.6), result('d1', 'D', 0.4, '2021'), result('d2', 'D', 0.4, '2021'), result('d3', 'D', 0.4, '2021'),
    ]);

  test('relevance is cumulative: the sum of a document\'s scores, highest first', () => {
    expect(groupRelevance(groups()[3])).toBeCloseTo(1.2);
    expect(sortDocumentGroups(groups(), 'relevance').map((g) => g.docId)).toEqual(['D', 'B', 'A', 'C']);
  });

  test('date is newest first with undated documents last, ties keeping search order', () => {
    expect(sortDocumentGroups(groups(), 'date').map((g) => g.docId)).toEqual(['B', 'D', 'A', 'C']);
    expect(documentYear(result('x', 'X', 0.1))).toBeNull();
    expect(documentYear(result('x', 'X', 0.1, '2020'))).toBe(2020);
  });

  test('does not mutate the input order', () => {
    const input = groups();
    sortDocumentGroups(input, 'date');
    expect(input.map((g) => g.docId)).toEqual(['A', 'B', 'C', 'D']);
  });
});
