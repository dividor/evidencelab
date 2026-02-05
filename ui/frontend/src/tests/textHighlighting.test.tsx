import React from 'react';
import { render } from '@testing-library/react';

import { SearchResult } from '../types/api';
import {
  findExactPhraseMatches,
  findWordMatches,
  parseSuperscripts,
  renderHighlightedText,
  renderTextWithInlineReferences,
} from '../utils/textHighlighting';

describe('textHighlighting utilities', () => {
  test('parseSuperscripts supports bracket and caret formats', () => {
    const text = 'See [^12], [3], and ^7 for details.';
    const { container } = render(<div>{parseSuperscripts(text)}</div>);

    const superscripts = container.querySelectorAll('sup.reference-number');
    expect(superscripts).toHaveLength(3);
    expect(superscripts[0].textContent).toBe('12');
    expect(superscripts[1].textContent).toBe('3');
    expect(superscripts[2].textContent).toBe('7');
    expect(container.textContent).not.toContain('[^12]');
    expect(container.textContent).not.toContain('^7');
  });

  test('renderTextWithInlineReferences renders inline reference superscripts', () => {
    const text = 'See [12] and ^7 for details.';
    const inlineRefs = [
      { number: 12, position: text.indexOf('12'), pattern: 'square_bracket' },
      { number: 7, position: text.indexOf('7'), pattern: 'geometric_caret' },
    ];

    const { container } = render(
      <div>{renderTextWithInlineReferences(text, '', inlineRefs)}</div>
    );

    const superscripts = container.querySelectorAll('sup.inline-reference-number');
    expect(superscripts).toHaveLength(2);
    expect(superscripts[0].textContent).toBe('12');
    expect(superscripts[1].textContent).toBe('7');
    expect(container.textContent).not.toContain('[12]');
    expect(container.textContent).not.toContain('^7');
  });

  test('findExactPhraseMatches finds overlapping phrases', () => {
    const matches = findExactPhraseMatches('test test', 'test');
    expect(matches).toHaveLength(2);
    expect(matches[0].matchedText).toBe('test');
    expect(matches[1].start).toBeGreaterThan(matches[0].start);
  });

  test('findWordMatches filters stop words and respects boundaries', () => {
    const matches = findWordMatches('Health in healthcare health.', 'health in the');
    expect(matches).toHaveLength(2);
    expect(matches[0].matchedText.toLowerCase()).toBe('health');
    expect(matches[1].matchedText.toLowerCase()).toBe('health');
  });

  test('renderHighlightedText uses semantic matches when enabled', () => {
    const text = 'Health and safety improved this year.';
    const result = {
      semanticMatches: [
        {
          start: 0,
          end: 0,
          matchedText: 'Health and safety',
          similarity: 0.9,
        },
      ],
    } as SearchResult;

    const nodes = renderHighlightedText(text, 'health', result, 'test');
    const { container } = render(<div>{nodes}</div>);
    const highlights = container.querySelectorAll('mark.search-highlight');
    expect(highlights).toHaveLength(1);
    expect(highlights[0].textContent).toContain('Health and safety');
  });
});
