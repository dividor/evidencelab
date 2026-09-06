import {
  ANCHOR_CONTEXT_CHARS,
  buildAnchor,
  isOrphaned,
  locateAnchor,
} from '../components/brief/briefCommentAnchors';

const TEXT =
  'Cash transfers improved food consumption scores. Market functionality ' +
  'gated the effect. Cash transfers improved dietary diversity less durably.';

describe('buildAnchor', () => {
  it('captures the selection with surrounding context', () => {
    const start = TEXT.indexOf('food consumption');
    const anchor = buildAnchor(TEXT, start, start + 'food consumption'.length);
    expect(anchor.quote).toBe('food consumption');
    expect(anchor.quotePrefix.endsWith('improved ')).toBe(true);
    expect(anchor.quoteSuffix.startsWith(' scores')).toBe(true);
  });

  it('clamps context at the start and end of the text', () => {
    const anchor = buildAnchor(TEXT, 0, 4);
    expect(anchor.quote).toBe('Cash');
    expect(anchor.quotePrefix).toBe('');
    const tail = buildAnchor(TEXT, TEXT.length - 3, TEXT.length);
    expect(tail.quoteSuffix).toBe('');
  });

  it('keeps context to the configured length', () => {
    const start = TEXT.indexOf('Market');
    const anchor = buildAnchor(TEXT, start, start + 6);
    expect(anchor.quotePrefix.length).toBeLessThanOrEqual(ANCHOR_CONTEXT_CHARS);
    expect(anchor.quoteSuffix.length).toBeLessThanOrEqual(ANCHOR_CONTEXT_CHARS);
  });
});

describe('locateAnchor', () => {
  it('finds a unique quote', () => {
    const range = locateAnchor(TEXT, { quote: 'Market functionality' });
    expect(range).not.toBeNull();
    expect(TEXT.slice(range!.start, range!.end)).toBe('Market functionality');
  });

  it('survives re-wrapped whitespace', () => {
    const rewrapped = TEXT.replace('food consumption', 'food\n   consumption');
    const range = locateAnchor(rewrapped, { quote: 'food consumption' });
    expect(range).not.toBeNull();
    expect(rewrapped.slice(range!.start, range!.end)).toBe('food\n   consumption');
  });

  it('uses context to pick between repeated phrases', () => {
    const second = TEXT.lastIndexOf('Cash transfers improved');
    const anchor = buildAnchor(TEXT, second, second + 'Cash transfers improved'.length);
    const range = locateAnchor(TEXT, anchor);
    expect(range!.start).toBe(second);
  });

  it('returns the first occurrence when there is no context to judge by', () => {
    const range = locateAnchor(TEXT, { quote: 'Cash transfers improved' });
    expect(range!.start).toBe(TEXT.indexOf('Cash transfers improved'));
  });

  it('returns null when the passage is gone', () => {
    expect(locateAnchor(TEXT, { quote: 'unrelated wording' })).toBeNull();
  });

  it('returns null for an empty quote or empty text', () => {
    expect(locateAnchor(TEXT, { quote: '' })).toBeNull();
    expect(locateAnchor('', { quote: 'anything' })).toBeNull();
  });
});

describe('isOrphaned', () => {
  it('is false while the quote is present', () => {
    expect(isOrphaned(TEXT, { quote: 'Market functionality' })).toBe(false);
  });

  it('is true once the section no longer contains it', () => {
    expect(isOrphaned('Entirely rewritten section.', { quote: 'Market functionality' })).toBe(
      true,
    );
  });

  it('is false for a whole-brief comment with no quote', () => {
    expect(isOrphaned(TEXT, { quote: null })).toBe(false);
  });
});
