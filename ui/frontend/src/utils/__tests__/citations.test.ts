/**
 * Unit tests for the shared citation utility — the single source of truth that
 * keeps the on-screen AI summary, the References list, and every export
 * agreeing on how `[N]` markers are parsed and renumbered.
 */
import {
  buildCitationSequenceMap,
  extractCitedNumbers,
  extractValidCitedNumbers,
  parseCitationNumbers,
} from '../citations';
import { SearchResult } from '../../types/api';

/** Build `n` minimal search results so citation numbers `1..n` resolve. */
const makeResults = (n: number): SearchResult[] =>
  Array.from({ length: n }, (_, i) => ({
    chunk_id: `c${i + 1}`,
    doc_id: `d${i + 1}`,
    text: `text ${i + 1}`,
    page_num: i + 1,
    headings: [],
    score: 1,
    title: `Doc ${i + 1}`,
  }));

describe('parseCitationNumbers', () => {
  test('parses a single number', () => {
    expect(parseCitationNumbers('3')).toEqual([3]);
  });
  test('parses a comma list with surrounding whitespace', () => {
    expect(parseCitationNumbers('1, 4,7')).toEqual([1, 4, 7]);
  });
});

describe('extractCitedNumbers', () => {
  test('returns unique numbers sorted ascending (citation order)', () => {
    expect(extractCitedNumbers('see [3], then [1] and [3] and [2, 5]')).toEqual([
      1, 2, 3, 5,
    ]);
  });
  test('returns [] when there are no markers', () => {
    expect(extractCitedNumbers('no citations here')).toEqual([]);
  });
});

describe('extractValidCitedNumbers', () => {
  test('keeps only numbers that resolve to a search result', () => {
    // 12 results → [8] and [10] are real; [19] is a hallucinated marker.
    expect(
      extractValidCitedNumbers('a [8] b [19] c [10]', makeResults(12)),
    ).toEqual([8, 10]);
  });
  test('drops numbers below 1 and above the result count', () => {
    expect(extractValidCitedNumbers('x [0] y [2] z [99]', makeResults(3))).toEqual([
      2,
    ]);
  });
  test('returns [] when no cited number resolves', () => {
    expect(extractValidCitedNumbers('only [5]', makeResults(2))).toEqual([]);
  });
});

describe('buildCitationSequenceMap', () => {
  test('maps each valid original number to its 1-based sequential position', () => {
    // Non-contiguous indices 2, 5, 9 renumber to 1, 2, 3 — the exact mapping
    // the on-screen summary applies and the docx export must mirror.
    const map = buildCitationSequenceMap('a [9] b [2] c [5]', makeResults(9));
    expect(map.get(2)).toBe(1);
    expect(map.get(5)).toBe(2);
    expect(map.get(9)).toBe(3);
    expect(map.size).toBe(3);
  });
  test('is an identity map when citations are already contiguous from 1', () => {
    const map = buildCitationSequenceMap('a [1] b [2] c [3]', makeResults(3));
    expect([...map.entries()]).toEqual([
      [1, 1],
      [2, 2],
      [3, 3],
    ]);
  });
  test('excludes hallucinated numbers so they get no display slot', () => {
    // Regression for the "fake references" bug: [19] has no backing result, so
    // it must not enter the map and must not consume a sequence slot — the real
    // citations [8] and [10] renumber cleanly to 1 and 2.
    const map = buildCitationSequenceMap(
      'claim [8] more [19] end [10]',
      makeResults(12),
    );
    expect(map.has(19)).toBe(false);
    expect(map.get(8)).toBe(1);
    expect(map.get(10)).toBe(2);
    expect(map.size).toBe(2);
  });
  test('drops trailing hallucinated numbers, leaving real ones unchanged', () => {
    // Mirrors the reported failure: the summary densely cites [1]..[3]
    // (an identity map) plus a hallucinated [9] when only 3 results exist.
    // The fake disappears; the real numbers keep their displayed values.
    const map = buildCitationSequenceMap(
      'one [1] two [2] three [3] fake [9]',
      makeResults(3),
    );
    expect([...map.entries()]).toEqual([
      [1, 1],
      [2, 2],
      [3, 3],
    ]);
    expect(map.has(9)).toBe(false);
  });
  test('returns an empty map when nothing is cited', () => {
    expect(buildCitationSequenceMap('nothing cited', makeResults(3)).size).toBe(0);
  });
});
