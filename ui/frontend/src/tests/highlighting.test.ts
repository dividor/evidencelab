/**
 * Unit tests for semantic highlighting functionality
 */

import { findSemanticMatches } from '../utils/textHighlighting';

// Mock fetch for testing
global.fetch = jest.fn();

describe('Semantic Highlighting', () => {
  beforeEach(() => {
    (fetch as jest.Mock).mockClear();
  });

  test('findSemanticMatches returns highlights from API', async () => {
    const phrase = 'The project used satellite data from GEMS.';
    const mockResponse = {
      matches: [
        {
          text: phrase
        }
      ]
    };

    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse
    });

    const text = 'Background text here. The project used satellite data from GEMS. More text follows.';
    const query = 'satellite';
    const threshold = 0.4;

    const result = await findSemanticMatches(text, query, threshold);

    expect(result).toHaveLength(1);
    expect(result[0].start).toBe(text.indexOf(phrase));
    expect(result[0].end).toBe(text.indexOf(phrase) + phrase.length);
    expect(result[0].matchedText).toBe(phrase);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/highlight'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          query: query,
          text: text,
          highlight_type: 'semantic',
          semantic_threshold: threshold
        })
      })
    );
  });

  test('findSemanticMatches handles empty response', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ matches: [] })
    });

    const result = await findSemanticMatches('Some text', 'query', 0.4);
    expect(result).toHaveLength(0);
  });

  test('findSemanticMatches handles API error gracefully', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      statusText: 'Internal Server Error'
    });

    const result = await findSemanticMatches('Some text', 'query', 0.4);
    expect(result).toHaveLength(0);
  });

  test('findSemanticMatches handles network error gracefully', async () => {
    (fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

    const result = await findSemanticMatches('Some text', 'query', 0.4);
    expect(result).toHaveLength(0);
  });

  test('findSemanticMatches returns empty array for empty query', async () => {
    const result = await findSemanticMatches('Some text', '', 0.4);
    expect(result).toHaveLength(0);
    expect(fetch).not.toHaveBeenCalled();
  });

  test('findSemanticMatches returns empty array for empty text', async () => {
    const result = await findSemanticMatches('', 'query', 0.4);
    expect(result).toHaveLength(0);
    expect(fetch).not.toHaveBeenCalled();
  });
});
