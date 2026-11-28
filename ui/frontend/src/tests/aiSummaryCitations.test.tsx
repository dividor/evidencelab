/**
 * Regression test for the "fake references" bug: the AI summary must never
 * render a citation number that has no backing search result. The LLM
 * occasionally emits an out-of-range marker (e.g. `[2]` when only one result
 * exists); such markers must be dropped, not shown as bare numbers.
 */
import React from 'react';
import { fireEvent, render } from '@testing-library/react';
import { AiSummaryPanel } from '../components/AiSummaryPanel';
import { AiSummaryWithCitations } from '../components/AiSummaryWithCitations';
import { AiSummaryReferences } from '../components/AiSummaryReferences';
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

test('summary citations open the original passages even when reranker scores are negative', () => {
  const results = makeResults(2);
  results[0].score = -0.82;
  const onResultClick = jest.fn();
  const { container } = render(
    <AiSummaryPanel
      enabled aiSummaryExpanded aiSummaryCollapsed={false} aiSummaryLoading={false}
      aiSummary="First finding [1]. Second finding [2]." results={results}
      aiPrompt="" showPromptModal={false} onResultClick={onResultClick}
      onOpenPrompt={jest.fn()} onClosePrompt={jest.fn()}
      onToggleExpanded={jest.fn()} onToggleCollapsed={jest.fn()}
    />,
  );
  const references = container.querySelectorAll('.ai-summary-ref-link');
  expect(references).toHaveLength(2);
  fireEvent.click(references[0]);
  fireEvent.click(references[1]);
  expect(onResultClick.mock.calls).toEqual([[results[0]], [results[1]]]);
});

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

describe('AiSummaryWithCitations — citation numbering', () => {
  test('inline citations count up 1, 2, 3… top to bottom', () => {
    // Regression: models cite results out of order (Nova 2 Lite first cited
    // results 1, 3, 15, 20, 11 for "Outcomes of Home-Grown School Feeding").
    // Numbering by result position showed 1, 3, 7, 8, 6 on screen.
    const summary = [
      '## Education',
      'Attendance rose [1]. Retention held [3].',
      '## Health',
      '- Anaemia fell [15].',
      '- Diets improved [20].',
      '## Economy',
      'Farmers sold more [11]. Enrolment again [1].',
    ].join('\n');
    const { container } = render(
      <AiSummaryWithCitations
        summaryText={summary}
        searchResults={makeResults(20)}
        onResultClick={() => undefined}
      />,
    );

    const shown = Array.from(container.querySelectorAll('.ai-summary-citation')).map(
      (badge) => badge.textContent,
    );
    expect(shown).toEqual(['1', '2', '3', '4', '5', '1']);
  });

  test('References list only what the visible summary cites, with the same numbers', () => {
    // Nova 2 Lite ends with a "Summary" section citing nearly every source,
    // which the screen hides. The References must not list those extra
    // sources, and inline [n] must point at the same document as reference n.
    const summary = [
      '## Findings',
      'Attendance rose [4]. Costs grew [2].',
      '## Summary',
      'Overall positive [1, 2, 3, 4, 5, 6].',
    ].join('\n');
    const results = makeResults(6);
    const { container } = render(
      <>
        <AiSummaryWithCitations
          summaryText={summary}
          searchResults={results}
          onResultClick={() => undefined}
        />
        <AiSummaryReferences summaryText={summary} results={results} onResultClick={() => undefined} />
      </>,
    );

    // Inline badges carry the cited document in their title; reference links
    // reuse the badge class without one.
    const inline = Array.from(container.querySelectorAll('.ai-summary-citation[title]')).map(
      (badge) => `${badge.textContent} ${badge.getAttribute('title')}`,
    );
    expect(inline).toEqual(['1 Doc 4 (Unknown)', '2 Doc 2 (Unknown)']);
    const groups = Array.from(container.querySelectorAll('.ai-summary-ref-group')).map(
      (group) => group.textContent,
    );
    expect(groups).toHaveLength(2);
    expect(groups[0]).toContain('Doc 4');
    expect(groups[0]).toContain('1');
    expect(groups[1]).toContain('Doc 2');
    expect(groups[1]).toContain('2');
  });
});
