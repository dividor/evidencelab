import { SourceReference } from '../types/api';

const mockFindSemanticMatches = jest.fn();
jest.mock('../utils/textHighlighting', () => ({
  ...jest.requireActual('../utils/textHighlighting'),
  findSemanticMatches: (...args: unknown[]) => mockFindSemanticMatches(...args),
}));

import {
  extractClaimForCitation,
  highlightSectionSources,
} from '../components/brief/briefHighlights';

const CONTENT =
  '# Findings\n\nCash transfers improved food consumption scores [1]. ' +
  'Effects on dietary diversity were smaller [2], fading within months [2][3]. ' +
  'Cost efficiency favoured cash in most comparisons [1, 3].';

const source = (index: number, text = `Excerpt for source ${index}.`): SourceReference => ({
  chunkId: `c${index}`,
  docId: `d${index}`,
  title: `Doc ${index}`,
  text,
  score: 0.9,
  index,
});

describe('extractClaimForCitation', () => {
  it('returns the sentence carrying the marker, stripped of markers and markdown', () => {
    const claim = extractClaimForCitation(CONTENT, 1);
    expect(claim).toContain('Cash transfers improved food consumption scores');
    expect(claim).toContain('Cost efficiency favoured cash');
    expect(claim).not.toContain('[1]');
    expect(claim).not.toContain('#');
  });

  it('matches a number inside a combined [n, m] marker', () => {
    const claim = extractClaimForCitation(CONTENT, 3);
    expect(claim).toContain('fading within months');
    expect(claim).toContain('Cost efficiency favoured cash');
    expect(claim).not.toContain('improved food consumption');
  });

  it('returns empty when the source is not cited', () => {
    expect(extractClaimForCitation(CONTENT, 9)).toBe('');
  });
});

describe('highlightSectionSources', () => {
  beforeEach(() => mockFindSemanticMatches.mockReset());

  it('attaches matches for cited sources and leaves failures as plain excerpts', async () => {
    mockFindSemanticMatches
      .mockResolvedValueOnce([{ start: 0, end: 7, matchedText: 'Excerpt' }])
      .mockRejectedValueOnce(new Error('LLM down'))
      .mockResolvedValueOnce([]);
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [source(1), source(2), source(3)],
      threshold: 0.6,
    });
    expect(out[0].semanticMatches).toEqual([{ start: 0, end: 7, matchedText: 'Excerpt' }]);
    expect(out[1].semanticMatches).toBeUndefined();
    expect(out[2].semanticMatches).toBeUndefined();
  });

  it('skips uncited sources and ones already highlighted', async () => {
    const already = { ...source(1), semanticMatches: [{ start: 1, end: 2 }] };
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [already, source(9)],
      threshold: 0.6,
    });
    expect(mockFindSemanticMatches).not.toHaveBeenCalled();
    expect(out[0].semanticMatches).toEqual([{ start: 1, end: 2 }]);
    expect(out[1].semanticMatches).toBeUndefined();
  });

  it('computes matches against the excerpt body after the breadcrumb line', async () => {
    mockFindSemanticMatches.mockResolvedValue([{ start: 0, end: 4 }]);
    await highlightSectionSources({
      content: CONTENT,
      sources: [source(1, '-- Chapter > Findings --\nBody text here.')],
      threshold: 0.6,
    });
    expect(mockFindSemanticMatches).toHaveBeenCalledWith(
      'Body text here.',
      expect.stringContaining('Cash transfers improved'),
      0.6,
      undefined,
    );
  });

  it('stops early when the run goes stale', async () => {
    mockFindSemanticMatches.mockResolvedValue([{ start: 0, end: 4 }]);
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [source(1), source(2)],
      threshold: 0.6,
      isStale: () => true,
    });
    expect(mockFindSemanticMatches).not.toHaveBeenCalled();
    expect(out).toHaveLength(2);
  });
});

describe('snapToWordBounds', () => {
  const { snapToWordBounds } = jest.requireActual('../components/citations/CitedContent');
  const text = 'The Kenya Certificate of Secondary Education results.';

  it('expands a mid-word start back to the word start', () => {
    const start = text.indexOf('tificate');
    const out = snapToWordBounds(text, start, text.indexOf('Education') + 9);
    expect(text.substring(out.start, out.end)).toBe('Certificate of Secondary Education');
  });

  it('expands a mid-word end forward to the word end', () => {
    const out = snapToWordBounds(text, text.indexOf('Kenya'), text.indexOf('Cert') + 4);
    expect(text.substring(out.start, out.end)).toBe('Kenya Certificate');
  });

  it('leaves boundaries already on word edges untouched', () => {
    const s = text.indexOf('Kenya');
    const out = snapToWordBounds(text, s, s + 'Kenya'.length);
    expect(out).toEqual({ start: s, end: s + 5 });
  });

  it('clamps out-of-range offsets', () => {
    const out = snapToWordBounds(text, -5, text.length + 10);
    expect(out.start).toBe(0);
    expect(out.end).toBe(text.length);
  });
});
