import { SUMMARY_RESULT_LIMIT, selectSummaryResults } from '../utils/summarySelection';
import { SearchResult } from '../types/api';

const result = (docId: string, n: number): SearchResult => ({
  chunk_id: `${docId}-c${n}`,
  doc_id: docId,
  text: `${docId} excerpt ${n}`,
  page_num: n,
  headings: [],
  score: 1 / n,
  title: docId,
  organization: 'WFP',
  year: '2024',
  metadata: {},
});

// Document-major, as wide search returns them: 3 excerpts each from A, B, C, D.
const wideResults = ['A', 'B', 'C', 'D'].flatMap((d) => [1, 2, 3].map((n) => result(d, n)));

describe('selectSummaryResults', () => {
  test('plain mode takes the top results as ranked', () => {
    const picked = selectSummaryResults(wideResults, false, 5);
    expect(picked.map((r) => r.chunk_id)).toEqual(['A-c1', 'A-c2', 'A-c3', 'B-c1', 'B-c2']);
  });

  test('wide mode takes the best excerpt of every document before any second excerpts', () => {
    const picked = selectSummaryResults(wideResults, true, 6);
    expect(picked.map((r) => r.chunk_id)).toEqual(['A-c1', 'B-c1', 'C-c1', 'D-c1', 'A-c2', 'B-c2']);
    expect(new Set(picked.map((r) => r.doc_id)).size).toBe(4);
  });

  test('wide mode keeps document order and within-document order', () => {
    const picked = selectSummaryResults(wideResults, true, 12);
    expect(picked.map((r) => r.doc_id).slice(0, 4)).toEqual(['A', 'B', 'C', 'D']);
    expect(picked.filter((r) => r.doc_id === 'C').map((r) => r.chunk_id)).toEqual(['C-c1', 'C-c2', 'C-c3']);
    expect(picked).toHaveLength(12);
  });

  test('wide mode stops when every document is exhausted', () => {
    const picked = selectSummaryResults(wideResults.slice(0, 5), true, 20);
    expect(picked).toHaveLength(5);
  });

  test('defaults to the summary result limit', () => {
    const many = Array.from({ length: 30 }, (_, i) => result(`D${i}`, 1));
    expect(selectSummaryResults(many, true)).toHaveLength(SUMMARY_RESULT_LIMIT);
    expect(selectSummaryResults(many, false)).toHaveLength(SUMMARY_RESULT_LIMIT);
  });

  test('results without a document id are kept as their own group', () => {
    const loose = [{ ...result('X', 1), doc_id: '' }, { ...result('X', 2), doc_id: '' }, result('Y', 1)];
    const picked = selectSummaryResults(loose, true, 3);
    expect(picked.map((r) => r.chunk_id)).toEqual(['X-c1', 'X-c2', 'Y-c1']);
  });
});
