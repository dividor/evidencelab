import { groupResultsByDocument } from '../utils/resultGrouping';
import type { SearchResult } from '../types/api';

const result = (chunkId: string, docId: string, score: number): SearchResult => ({
  chunk_id: chunkId, doc_id: docId, text: 't', page_num: 1, headings: [], score, title: `Doc ${docId}`, metadata: {},
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
