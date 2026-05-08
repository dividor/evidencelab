import React from 'react';
import { render } from '@testing-library/react';

import { SearchResult } from '../types/api';
import {
  findExactPhraseMatches,
  findSemanticMatches,
  findWordMatches,
  highlightTextWithAPI,
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

  describe('AbortSignal support', () => {
    let originalFetch: typeof global.fetch;

    beforeEach(() => {
      originalFetch = global.fetch;
    });

    afterEach(() => {
      global.fetch = originalFetch;
      jest.restoreAllMocks();
    });

    test('highlightTextWithAPI forwards AbortSignal to fetch', async () => {
      const mockFetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ highlighted_text: 'x', matches: [] })
      });
      global.fetch = mockFetch as unknown as typeof global.fetch;

      const controller = new AbortController();
      await highlightTextWithAPI('some text', 'query', 'semantic', 0.4, null, controller.signal);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const fetchInit = mockFetch.mock.calls[0][1];
      expect(fetchInit.signal).toBe(controller.signal);
    });

    test('highlightTextWithAPI re-throws AbortError so callers can detect cancellation', async () => {
      const abortError = Object.assign(new Error('aborted'), { name: 'AbortError' });
      global.fetch = jest.fn().mockRejectedValue(abortError) as unknown as typeof global.fetch;

      await expect(
        highlightTextWithAPI('text', 'query', 'semantic', 0.4)
      ).rejects.toMatchObject({ name: 'AbortError' });
    });

    test('highlightTextWithAPI swallows non-abort errors and returns empty', async () => {
      global.fetch = jest.fn().mockRejectedValue(new Error('network down')) as unknown as typeof global.fetch;
      jest.spyOn(console, 'error').mockImplementation(() => undefined);

      const result = await highlightTextWithAPI('text', 'query');
      expect(result).toEqual({ highlighted_text: 'text', matches: [] });
    });

    test('findSemanticMatches threads AbortSignal through to highlightTextWithAPI', async () => {
      const mockFetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ matches: [] })
      });
      global.fetch = mockFetch as unknown as typeof global.fetch;

      const controller = new AbortController();
      await findSemanticMatches('text', 'query', 0.4, null, controller.signal);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch.mock.calls[0][1].signal).toBe(controller.signal);
    });
  });
});
