import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CitedMarkdown } from '../components/citations/CitedContent';
import { SourceReference } from '../types/api';

const source: SourceReference = {
  chunkId: 'c1',
  docId: 'd1',
  title: 'Doc One',
  text: 'First line ^1 of the excerpt.\nSecond line continues.',
  score: 0.5,
  page: 4,
  index: 1,
  headings: [],
};

const claimSource: SourceReference = {
  ...source,
  text: 'The GoK  commitment to  education is articulated in the Constitution [^56] .',
  claimMatches: [
    {
      claim: 'a key finding',
      matches: [
        { start: 0, end: 31, matchedText: 'The GoK commitment to education' },
      ],
    },
  ],
};

describe('inline citation hover card', () => {
  test('renders the excerpt with the same formatter Search uses', () => {
    const { container } = render(<CitedMarkdown content="A key finding [1]." sources={[source]} />);

    const badge = container.querySelector('.ai-summary-citation') as HTMLElement;
    expect(badge).not.toBeNull();
    fireEvent.mouseEnter(badge);

    // Card shows the document title + page…
    expect(screen.getByText('Doc One')).toBeInTheDocument();
    expect(screen.getByText('Page 4')).toBeInTheDocument();

    // …and the excerpt is rendered through Search's parseAndRenderSuperscripts,
    // which wraps it in a .formatted-text-block (not raw text), so the two match.
    const excerpt = document.querySelector('.citation-hover-excerpt');
    expect(excerpt).not.toBeNull();
    expect(excerpt!.querySelector('.formatted-text-block')).not.toBeNull();
  });

  test('marks the span supporting the hovered claim and tidies the chunk', () => {
    const { container } = render(
      <CitedMarkdown content="A key finding [1]." sources={[claimSource]} />,
    );
    fireEvent.mouseEnter(container.querySelector('.ai-summary-citation') as HTMLElement);

    const excerpt = document.querySelector('.citation-hover-excerpt') as HTMLElement;
    const mark = excerpt.querySelector('mark');
    expect(mark).not.toBeNull();
    expect(mark!.textContent).toContain('commitment to education');
    // Footnote markers and PDF double-spacing are cleaned up for reading.
    expect(excerpt.textContent).not.toContain('[^56]');
    expect(excerpt.textContent).not.toMatch(/ {2,}/);
  });
});
