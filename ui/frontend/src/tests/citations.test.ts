import {
  buildCitationSequenceMap,
  extractCitedNumbers,
  parseCitationNumbers,
} from '../utils/citations';
import { buildGroupedReferences } from '../components/AiSummaryReferences';
import { SearchResult } from '../types/api';

const makeResult = (over: Partial<SearchResult>): SearchResult => ({
  chunk_id: 'chunk',
  doc_id: 'doc',
  text: '',
  page_num: 0,
  headings: [],
  score: 1,
  title: 'Untitled',
  metadata: {},
  ...over,
});

describe('citations util', () => {
  describe('parseCitationNumbers', () => {
    it('parses_a_single_number', () => {
      expect(parseCitationNumbers('3')).toEqual([3]);
    });

    it('parses_a_comma_separated_group_with_spaces', () => {
      expect(parseCitationNumbers('2, 5,7')).toEqual([2, 5, 7]);
    });
  });

  describe('extractCitedNumbers', () => {
    it('returns_unique_numbers_sorted_ascending', () => {
      const summary = 'Alpha [3] beta [1] gamma [3].';
      expect(extractCitedNumbers(summary)).toEqual([1, 3]);
    });

    it('expands_multi_number_markers', () => {
      const summary = 'Finding one [2, 5] and finding two [1].';
      expect(extractCitedNumbers(summary)).toEqual([1, 2, 5]);
    });

    it('returns_empty_array_when_no_citations_present', () => {
      expect(extractCitedNumbers('No citations here.')).toEqual([]);
    });
  });

  describe('buildCitationSequenceMap', () => {
    it('maps_original_numbers_to_1_based_sequence_in_ascending_order', () => {
      const summary = 'See [7] and [3] and again [3] plus [1].';
      const map = buildCitationSequenceMap(summary);
      expect(Array.from(map.entries())).toEqual([
        [1, 1],
        [3, 2],
        [7, 3],
      ]);
    });

    it('does_not_share_regex_state_between_calls', () => {
      const summary = 'Repeated [1] usage [2].';
      // Calling twice must yield identical results (guards against shared
      // RegExp lastIndex state leaking across invocations).
      expect(Array.from(buildCitationSequenceMap(summary).entries())).toEqual(
        Array.from(buildCitationSequenceMap(summary).entries())
      );
    });
  });
});

describe('buildGroupedReferences', () => {
  it('resolves_citation_N_to_the_Nth_result_one_based', () => {
    const results = [
      makeResult({ title: 'First Doc', organization: 'Org A', year: '2020', page_num: 4 }),
      makeResult({ title: 'Second Doc', organization: 'Org B', year: '2021', page_num: 9 }),
    ];
    const groups = buildGroupedReferences('Claim one [1]. Claim two [2].', results);

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ title: 'First Doc', organization: 'Org A', year: '2020' });
    expect(groups[0].refs[0]).toMatchObject({ sequential: 1 });
    expect(groups[0].refs[0].result.page_num).toBe(4);
    expect(groups[1]).toMatchObject({ title: 'Second Doc', organization: 'Org B', year: '2021' });
    expect(groups[1].refs[0]).toMatchObject({ sequential: 2 });
  });

  it('groups_multiple_citations_of_the_same_document_together', () => {
    const results = [
      makeResult({ title: 'Shared Doc', page_num: 1 }),
      makeResult({ title: 'Shared Doc', page_num: 2 }),
      makeResult({ title: 'Other Doc', page_num: 3 }),
    ];
    const groups = buildGroupedReferences('A [1] B [2] C [3].', results);

    expect(groups).toHaveLength(2);
    expect(groups[0].title).toBe('Shared Doc');
    expect(groups[0].refs.map((r) => r.sequential)).toEqual([1, 2]);
    expect(groups[1].title).toBe('Other Doc');
    expect(groups[1].refs.map((r) => r.sequential)).toEqual([3]);
  });

  it('skips_out_of_range_citation_numbers_without_throwing', () => {
    const results = [makeResult({ title: 'Only Doc' })];
    const groups = buildGroupedReferences('Valid [1] but dangling [5].', results);

    expect(groups).toHaveLength(1);
    expect(groups[0].title).toBe('Only Doc');
    expect(groups[0].refs[0].sequential).toBe(1);
  });

  it('reference_sequentials_match_the_shared_sequence_map', () => {
    // Inline citations (AiSummaryWithCitations / exportResearch) and the reference
    // list (buildGroupedReferences) must agree on the displayed number for every
    // citation, on screen and in the export.
    const results = [
      makeResult({ title: 'Doc 1' }),
      makeResult({ title: 'Doc 2' }),
      makeResult({ title: 'Doc 3' }),
    ];
    const summary = 'X [3] Y [1] Z [2].';
    const sequenceMap = buildCitationSequenceMap(summary);

    const groups = buildGroupedReferences(summary, results);
    for (const group of groups) {
      for (const ref of group.refs) {
        // result lives at index (origNum - 1); recover origNum from its position.
        const origNum = results.indexOf(ref.result) + 1;
        expect(ref.sequential).toBe(sequenceMap.get(origNum));
      }
    }
  });
});

describe('citation discrepancy regression (#337080)', () => {
  it('resolves_citations_against_the_full_result_array_not_a_score_filtered_one', () => {
    // The summary text is generated against the FULL result array sent to the LLM,
    // where citation [2] indexes the second result. The on-screen summary previously
    // re-indexed citations into a minScore-filtered array, so [2] resolved to the
    // wrong document (or was dropped). This asserts the correct, full-array mapping
    // and demonstrates why the filtered array must NOT be used.
    const fullResults = [
      makeResult({ title: 'Low Relevance Doc', score: 0.1 }),
      makeResult({ title: 'Cited Doc', score: 0.9 }),
    ];
    const summary = 'Key finding [2].';

    // Correct behaviour (post-fix): resolve against the full array.
    const correct = buildGroupedReferences(summary, fullResults);
    expect(correct).toHaveLength(1);
    expect(correct[0].title).toBe('Cited Doc');

    // Old behaviour: filtering by score first shifts indices so [2] no longer maps
    // to "Cited Doc" — proving the bug the fix removes.
    const minScore = 0.5;
    const filtered = fullResults.filter((r) => r.score >= minScore);
    const buggy = buildGroupedReferences(summary, filtered);
    // "Cited Doc" is now at index 0, so citation [2] points past the array and is
    // dropped — the on-screen references diverged from the export.
    expect(buggy.some((g) => g.title === 'Cited Doc')).toBe(false);
  });
});
