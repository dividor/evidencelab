/**
 * Unit tests for the shared citation utility — the single source of truth that
 * keeps the on-screen AI summary, the References list, and every export
 * agreeing on how `[N]` markers are parsed and renumbered.
 */
import {
  buildCitationSequenceMap,
  extractCitedNumbers,
  parseCitationNumbers,
} from '../citations';

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

describe('buildCitationSequenceMap', () => {
  test('maps each original number to its 1-based sequential position', () => {
    // Non-contiguous indices 2, 5, 9 renumber to 1, 2, 3 — the exact mapping
    // the on-screen summary applies and the docx export must mirror.
    const map = buildCitationSequenceMap('a [9] b [2] c [5]');
    expect(map.get(2)).toBe(1);
    expect(map.get(5)).toBe(2);
    expect(map.get(9)).toBe(3);
    expect(map.size).toBe(3);
  });
  test('is an identity map when citations are already contiguous from 1', () => {
    const map = buildCitationSequenceMap('a [1] b [2] c [3]');
    expect([...map.entries()]).toEqual([
      [1, 1],
      [2, 2],
      [3, 3],
    ]);
  });
  test('returns an empty map when nothing is cited', () => {
    expect(buildCitationSequenceMap('nothing cited').size).toBe(0);
  });
});
