// Coverage for the literal-text matcher inside PDFViewer:
//   - normalizePdfText / normalizePdfTextNoSpaces collapse decomposed
//     Unicode (e.g., n + combining tilde) into their precomposed forms.
//   - findTextMatchesOnPage: a multi-word query whose space lines up with a
//     synthetic gap between adjacent PDF text items is now MATCHED (was
//     silently dropped). False-positive cross-item matches (where the user's
//     query has no space at the gap position) still get rejected.

import {
  findTextMatchesOnPage,
  normalizePdfText,
  normalizePdfTextNoSpaces
} from '../components/PDFViewer';

// PDF.js text items have shape { str, width, transform: [a,b,c,d,e,f] }.
// Helper to build minimal mocks; positions are page-local.
const item = (str: string, x: number, y: number, width: number, height = 12) => ({
  str,
  width,
  height,
  transform: [height, 0, 0, height, x, y]
});

describe('normalizePdfText / normalizePdfTextNoSpaces — NFC handling', () => {
  test('decomposed n + combining tilde collapses to ñ (precomposed)', () => {
    const decomposed = 'El Niño';                   // "El Niño" with U+006E + U+0303
    const precomposed = 'El Niño';                   // "El Niño" with U+00F1
    expect(normalizePdfText(decomposed)).toBe(normalizePdfText(precomposed));
    expect(normalizePdfText(decomposed)).toContain('ñ');
    expect(normalizePdfText(decomposed)).not.toContain('̃');
  });

  test('no-spaces variant also NFC-normalizes', () => {
    const decomposed = 'Café';                      // "Café" decomposed
    const precomposed = 'Café';                      // "Café" precomposed
    expect(normalizePdfTextNoSpaces(decomposed)).toBe(normalizePdfTextNoSpaces(precomposed));
    expect(normalizePdfTextNoSpaces(decomposed)).toBe('café');
  });

  test('plain ASCII text is unchanged by NFC normalization', () => {
    expect(normalizePdfText('hello world')).toBe('hello world');
  });
});

describe('findTextMatchesOnPage — synthetic-gap crossing', () => {
  test('matches "el niño" when split across two items with no whitespace between (BUG REGRESSION)', () => {
    // PDF.js commonly splits "El Niño" into ["El", "Niño"] at a kerning
    // boundary. Without our fix, the synthetic-space gap causes the match
    // to be silently dropped. With the fix, the search term's space lines
    // up with the synthetic position, so the match is allowed.
    const items = [
      item('El', 100, 500, 10),
      item('Niño', 112, 500, 24)
    ];
    const matches = findTextMatchesOnPage(items, 'el niño', 1);

    expect(matches).toHaveLength(1);
    expect(matches[0].page).toBe(1);
    expect(matches[0].bbox.l).toBeCloseTo(100, 1);   // left edge of "El"
    expect(matches[0].bbox.r).toBeGreaterThan(112);  // right edge inside "Niño"
    expect(matches[0].isTextMatch).toBe(true);
  });

  test('still rejects false cross-item matches where the term has no space at the gap (REGRESSION GUARD)', () => {
    // Original bug example from the comment: "of"+"MOH" must NOT match "fmoh".
    const items = [
      item('of', 100, 500, 10),
      item('MOH', 112, 500, 18)
    ];
    const matches = findTextMatchesOnPage(items, 'fmoh', 1);
    expect(matches).toHaveLength(0);
  });

  test('matches NFC-decomposed PDF text against precomposed query', () => {
    // PDF stores ñ as decomposed (n + combining tilde). User types ñ as
    // precomposed (single codepoint). They must still match.
    const items = [
      item('El', 100, 500, 10),
      item('Niño', 112, 500, 24)         // decomposed
    ];
    const matches = findTextMatchesOnPage(items, 'el niño', 1);   // precomposed
    expect(matches).toHaveLength(1);
  });

  test('matches NFC-precomposed PDF text against decomposed query (symmetric)', () => {
    const items = [
      item('El', 100, 500, 10),
      item('Niño', 112, 500, 24)          // precomposed
    ];
    const matches = findTextMatchesOnPage(items, 'el niño', 1);   // decomposed
    expect(matches).toHaveLength(1);
  });

  test('finds a single-item literal match (no gap involved) — basic case still works', () => {
    const items = [item('El Niño', 100, 500, 35)];
    const matches = findTextMatchesOnPage(items, 'el niño', 1);
    expect(matches).toHaveLength(1);
    expect(matches[0].bbox.l).toBeCloseTo(100, 1);
  });

  test('finds multiple occurrences across the page', () => {
    // Three occurrences, two of them split across items.
    const items = [
      item('El Niño in 2015. Then', 50, 500, 100),
      item('El', 50, 480, 10),
      item('Niño', 62, 480, 24),
      item('arrived again. El', 50, 460, 80),
      item('Niño', 132, 460, 24)
    ];
    const matches = findTextMatchesOnPage(items, 'el niño', 1);
    expect(matches.length).toBeGreaterThanOrEqual(3);
  });

  test('returns no matches when items are empty', () => {
    expect(findTextMatchesOnPage([], 'el niño', 1)).toEqual([]);
  });
});
