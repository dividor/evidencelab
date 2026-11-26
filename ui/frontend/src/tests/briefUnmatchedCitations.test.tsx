/**
 * Citations a brief's API could not match to a source come back as `[?n]`
 * (the research agent cited a number it was never given). The section text
 * shows each as a red number badge, and the section's warning names them as
 * chips that jump to where they are cited.
 */
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CitedMarkdown } from '../components/citations/CitedContent';
import { UnresolvedCitationsWarning } from '../components/brief/BriefDocument';
import { SourceReference } from '../types/api';

const source: SourceReference = {
  chunkId: 'c7',
  docId: 'd7',
  title: 'Doc Seven',
  text: 'Teachers were trained.',
  score: 0.5,
  page: 3,
  index: 7,
  headings: [],
};

const SECTION_TEXT =
  'Teachers were trained [7][?143]. Committees met [1][?163]. Curricula changed [7][?143].';

const renderSection = (onOpenLog?: () => void) =>
  render(
    <section className="brief-doc-section">
      <UnresolvedCitationsWarning
        unresolved={[
          { n: 143, reason: 'no-source' },
          { n: 163, reason: 'no-source' },
        ]}
        canOpenLog={onOpenLog !== undefined}
        onOpenLog={onOpenLog}
      />
      <CitedMarkdown content={SECTION_TEXT} sources={[source]} />
    </section>,
  );

describe('a citation with no source in the text', () => {
  test('shows the citation number in a red badge', () => {
    const { container } = render(
      <CitedMarkdown content="Teachers were trained [7][?143]." sources={[source]} />,
    );
    const badge = container.querySelector('.citation-unmatched[data-unmatched="143"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe('143 (no source)');
    expect(badge!.querySelector('.visually-hidden')!.textContent).toBe(' (no source)');
    expect(badge!.getAttribute('title')).toMatch(/never given/);
    expect(container.textContent).not.toContain('[?143]');
    // The matched citation beside it still renders as a normal citation.
    expect(container.querySelector('.ai-summary-citation')!.textContent).toBe('7');
  });
});

describe('the unmatched-citation warning', () => {
  let scrolled: Element[];
  beforeEach(() => {
    scrolled = [];
    Element.prototype.scrollIntoView = jest.fn(function (this: Element) {
      scrolled.push(this);
    });
  });

  test('names each unmatched number as a chip', () => {
    renderSection();
    expect(screen.getByText('2 citations have no source')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Show where citation 143 has no source' }),
    ).toHaveTextContent('143');
    expect(
      screen.getByRole('button', { name: 'Show where citation 163 has no source' }),
    ).toBeInTheDocument();
  });

  test('a chip jumps to its citation, then to its next use on each click', () => {
    const { container } = renderSection();
    const uses = container.querySelectorAll('section > :not([role="status"]) .citation-unmatched[data-unmatched="143"]');
    expect(uses).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Show where citation 143 has no source' }));
    expect(scrolled).toEqual([uses[0]]);
    expect(uses[0]).toHaveClass('citation-unmatched-flash');

    fireEvent.click(screen.getByRole('button', { name: 'Show where citation 143 has no source' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show where citation 143 has no source' }));
    expect(scrolled).toEqual([uses[0], uses[1], uses[0]]);
  });

  test('links to the original output when the section has a log', () => {
    const onOpenLog = jest.fn();
    renderSection(onOpenLog);
    fireEvent.click(screen.getByRole('button', { name: 'See its original output' }));
    expect(onOpenLog).toHaveBeenCalledTimes(1);
  });

  test('without a log, says where the original output is', () => {
    renderSection();
    expect(screen.queryByRole('button', { name: 'See its original output' })).toBeNull();
    expect(screen.getByText(/Section History has its original output/)).toBeInTheDocument();
  });

  test('shows nothing when every citation has a source', () => {
    const { container } = render(<UnresolvedCitationsWarning unresolved={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
