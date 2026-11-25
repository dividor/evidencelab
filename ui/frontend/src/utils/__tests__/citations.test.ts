/**
 * Unit tests for the shared citation utility — the single source of truth that
 * keeps the on-screen AI summary, the References list, and every export
 * agreeing on how `[N]` markers are parsed and renumbered.
 */
import {
  buildCitationSequenceMap,
  buildGroupedReferences,
  extractCitedNumbers,
  extractValidCitedNumbers,
  parseCitationNumbers,
} from '../citations';
import { buildCitationLinks } from '../exportResearch';
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
  test('returns unique numbers in order of first appearance (reading order)', () => {
    expect(extractCitedNumbers('see [3], then [1] and [3] and [2, 5]')).toEqual([
      3, 1, 2, 5,
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
  test('numbers citations 1, 2, 3… in the order they first appear', () => {
    // Non-contiguous indices 9, 2, 5 renumber to 1, 2, 3 in reading order —
    // the exact mapping the on-screen summary applies and the exports mirror.
    const map = buildCitationSequenceMap('a [9] b [2] c [5]', makeResults(9));
    expect(map.get(9)).toBe(1);
    expect(map.get(2)).toBe(2);
    expect(map.get(5)).toBe(3);
    expect(map.size).toBe(3);
  });
  test('reads 1, 2, 3… top to bottom when the model cites out of result order', () => {
    // Regression: Nova 2 Lite's summary for "Outcomes of Home-Grown School
    // Feeding" first cited results 1, 3, 15, 20, 11, 6, 10, 2 (measured
    // 2026-11-25). Numbering by result position showed 1, 3, 7, 8, 6, 4, 5, 2.
    const summary =
      'Attendance rose [1]. Retention held [3]. Anaemia fell [15, 20]. ' +
      'Farmers sold more [11]. Costs [6] and delays [10]. Enrolment again [1, 2].';
    const map = buildCitationSequenceMap(summary, makeResults(20));
    const readingOrder: number[] = [];
    const re = /\[(\d+(?:,\s*\d+)*)\]/g;
    let match;
    while ((match = re.exec(summary)) !== null) {
      parseCitationNumbers(match[1]).forEach((n) => readingOrder.push(map.get(n)!));
    }
    expect(readingOrder).toEqual([1, 2, 3, 4, 5, 6, 7, 1, 8]);
  });
  test('numbers a multi-citation marker in the order it is written', () => {
    const map = buildCitationSequenceMap('both [5, 2]', makeResults(5));
    expect(map.get(5)).toBe(1);
    expect(map.get(2)).toBe(2);
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

describe('buildGroupedReferences', () => {
  test('lists documents in reading order with matching sequential numbers', () => {
    const groups = buildGroupedReferences('x [4] y [2] z [4, 1]', makeResults(4));
    expect(groups.map((g) => g.title)).toEqual(['Doc 4', 'Doc 2', 'Doc 1']);
    expect(groups.map((g) => g.refs.map((r) => r.sequential))).toEqual([[1], [2], [3]]);
  });
});

describe('buildCitationLinks (research HTML export)', () => {
  test('uses the same sequential numbers as the on-screen summary', () => {
    const summary = 'a [3] b [1] c [2]';
    const results = makeResults(3);
    const links = buildCitationLinks(summary, results);
    const onScreen = buildCitationSequenceMap(summary, results);
    expect([...links.entries()].map(([n, l]) => [n, l.seq])).toEqual([...onScreen.entries()]);
    expect(links.get(3)!.seq).toBe(1);
  });
});
