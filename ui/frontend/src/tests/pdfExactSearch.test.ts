import { findTextMatchesOnPage } from '../components/PDFViewer';

// Build a minimal pdf.js-style text item. transform = [a,b,c,d,e,f] where
// e (index 4) is x, f (index 5) is y, and d (index 3) drives the height.
const item = (str: string, x: number, width: number, height = 12) => ({
  str,
  transform: [height, 0, 0, height, x, 700],
  width,
  height,
});

describe('exact in-document search: findTextMatchesOnPage', () => {
  test('finds a literal match within a text item (case-insensitive)', () => {
    const items = [item('Ministry of Health', 72, 108)]; // 18 chars, avg width 6
    const matches = findTextMatchesOnPage(items, 'health', 1);

    expect(matches).toHaveLength(1);
    expect(matches[0].page).toBe(1);
    expect(matches[0].isTextMatch).toBe(true);
    expect(matches[0].text).toBe('Health'); // original casing preserved
    // 'Health' starts at char index 12 -> x = 72 + 12*(108/18) = 144
    expect(matches[0].bbox.l).toBeCloseTo(144, 1);
    expect(matches[0].bbox.r).toBeCloseTo(180, 1);
  });

  test('returns no matches when the term is absent', () => {
    const items = [item('Ministry of Health', 72, 108)];
    expect(findTextMatchesOnPage(items, 'finance', 1)).toHaveLength(0);
  });

  test('does not match across the synthetic gap between adjacent items', () => {
    // pdf.js often splits runs; a synthetic space is inserted so "of"+"Health"
    // never falsely matches a term that spans the boundary.
    const items = [item('of', 50, 14), item('Health', 70, 42)];
    expect(findTextMatchesOnPage(items, 'f he', 1)).toHaveLength(0);
  });

  test('still matches a term fully inside the second item', () => {
    const items = [item('of', 50, 14), item('Health', 70, 42)];
    const matches = findTextMatchesOnPage(items, 'health', 1);
    expect(matches).toHaveLength(1);
    expect(matches[0].text).toBe('Health');
  });
});
