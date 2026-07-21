/**
 * Regression test for the "fake references" bug: the AI summary must never
 * render a citation number that has no backing search result. The LLM
 * occasionally emits an out-of-range marker (e.g. `[2]` when only one result
 * exists); such markers must be dropped, not shown as bare numbers.
 */
import React from 'react';
import { render } from '@testing-library/react';
import { AiSummaryWithCitations } from '../components/AiSummaryWithCitations';
import { SearchResult } from '../types/api';

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

describe('AiSummaryWithCitations — hallucinated citations', () => {
  test('renders real citations but drops out-of-range markers', () => {
    // Only one result exists, so [1] is real and [2] is hallucinated.
    const summary =
      'Privacy gaps exist at country level [1]. Enforcement is inconsistent [2].';
    const { container } = render(
      <AiSummaryWithCitations
        summaryText={summary}
        searchResults={makeResults(1)}
        onResultClick={() => undefined}
      />,
    );

    const badges = container.querySelectorAll('.ai-summary-citation');
    expect(badges).toHaveLength(1);
    expect(badges[0].textContent).toBe('1');

    // The orphan number must not survive anywhere in the rendered output,
    // while the surrounding prose is preserved.
    expect(container.textContent).toContain('Enforcement is inconsistent');
    expect(container.textContent).not.toContain('2');
  });
});
