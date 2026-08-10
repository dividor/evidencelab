import { SourceReference } from '../types/api';

const mockFindSemanticMatches = jest.fn();
jest.mock('../utils/textHighlighting', () => ({
  ...jest.requireActual('../utils/textHighlighting'),
  findSemanticMatches: (...args: unknown[]) => mockFindSemanticMatches(...args),
}));

import {
  extractClaimsForCitation,
  highlightSectionSources,
} from '../components/brief/briefHighlights';

const CONTENT =
  '# Findings\n\nCash transfers improved food consumption scores [1]. ' +
  'Effects on dietary diversity were smaller [2], fading within months [2][3]. ' +
  'Cost efficiency favoured cash in most comparisons [1, 3].';

const LONG_MATCH = { start: 0, end: 40, matchedText: 'x'.repeat(40) };

const source = (index: number, text = `Excerpt for source ${index}.`): SourceReference => ({
  chunkId: `c${index}`,
  docId: `d${index}`,
  title: `Doc ${index}`,
  text,
  score: 0.9,
  index,
});

describe('extractClaimsForCitation', () => {
  it('returns one entry per citing sentence, stripped of markers and markdown', () => {
    const claims = extractClaimsForCitation(CONTENT, 1);
    expect(claims).toHaveLength(2);
    expect(claims[0].prose).toContain('cash transfers improved food consumption scores');
    expect(claims[1].prose).toContain('cost efficiency favoured cash');
    for (const c of claims) {
      expect(c.prose).not.toContain('[1]');
      expect(c.prose).not.toContain('#');
    }
  });

  it('matches a number inside a combined [n, m] marker', () => {
    const claims = extractClaimsForCitation(CONTENT, 3);
    expect(claims.map((c) => c.prose).join(' ')).toContain('fading within months');
    expect(claims.map((c) => c.prose).join(' ')).toContain('cost efficiency favoured cash');
    expect(claims.map((c) => c.prose).join(' ')).not.toContain('improved food consumption');
  });

  it('returns empty when the source is not cited', () => {
    expect(extractClaimsForCitation(CONTENT, 9)).toEqual([]);
  });
});

describe('highlightSectionSources', () => {
  beforeEach(() => mockFindSemanticMatches.mockReset());

  it('attaches per-claim matches for cited sources; failures keep plain excerpts', async () => {
    // Source 1 is cited from two sentences → two claim entries.
    mockFindSemanticMatches
      .mockResolvedValueOnce([LONG_MATCH])
      .mockResolvedValueOnce([{ ...LONG_MATCH, start: 5, end: 45 }])
      .mockRejectedValueOnce(new Error('LLM down'))
      .mockResolvedValue([]);
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [source(1), source(2), source(3)],
      threshold: 0.6,
    });
    expect(out[0].claimMatches).toHaveLength(2);
    expect(out[0].claimMatches?.[0].claim).toContain('cash transfers improved');
    expect(out[0].claimMatches?.[0].matches).toEqual([LONG_MATCH]);
    expect(out[1].claimMatches).toBeUndefined();
    expect(out[2].claimMatches).toBeUndefined();
  });

  it('drops fragment matches below the minimum length', async () => {
    mockFindSemanticMatches.mockResolvedValue([{ start: 0, end: 10 }]);
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [source(2)],
      threshold: 0.6,
    });
    expect(out[0].claimMatches).toBeUndefined();
  });

  it('skips uncited sources and ones already highlighted', async () => {
    const already = {
      ...source(1),
      claimMatches: [{ claim: 'x', matches: [{ start: 1, end: 2 }] }],
    };
    const out = await highlightSectionSources({
      content: CONTENT,
      sources: [already, source(9)],
      threshold: 0.6,
    });
    expect(mockFindSemanticMatches).not.toHaveBeenCalled();
    expect(out[0].claimMatches).toEqual([{ claim: 'x', matches: [{ start: 1, end: 2 }] }]);
    expect(out[1].claimMatches).toBeUndefined();
  });

  it('computes matches against the excerpt body after the breadcrumb line', async () => {
    mockFindSemanticMatches.mockResolvedValue([LONG_MATCH]);
    await highlightSectionSources({
      content: CONTENT,
      sources: [source(1, '-- Chapter > Findings --\nBody text here.')],
      threshold: 0.6,
    });
    expect(mockFindSemanticMatches).toHaveBeenCalledWith(
      'Body text here.',
      expect.stringContaining('cash transfers improved'),
      0.6,
      undefined,
    );
  });

  it('stops early when the run goes stale', async () => {
    mockFindSemanticMatches.mockResolvedValue([LONG_MATCH]);
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

describe('claim selection in the hover card (matchesForClaim via normalize/sentence)', () => {
  const { normalizeClaimText, sentenceAround } = jest.requireActual(
    '../components/citations/CitedContent',
  );

  it('normalizes render-time sentences to the same key as enrichment-time claims', () => {
    const enrichKey = extractClaimsForCitation(CONTENT, 1)[0].key;
    const renderSentence = sentenceAround(
      'Cash transfers improved food consumption scores [1]. Effects were smaller [2].',
      48,
    );
    expect(normalizeClaimText(renderSentence)).toBe(enrichKey);
  });

  it('sentenceAround isolates the sentence containing the marker position', () => {
    const text = 'First sentence here. Second one cites [3]. Third sentence.';
    expect(sentenceAround(text, text.indexOf('[3]'))).toBe('Second one cites [3].');
  });
});
