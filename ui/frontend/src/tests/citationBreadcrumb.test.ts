import { parseSectionBreadcrumb } from '../components/citations/CitedContent';

describe('parseSectionBreadcrumb', () => {
  test('splits a leading "-- a > b > c --" breadcrumb off the body, stripping the dashes', () => {
    const text =
      '-- 2. Evaluation findings > 2.5. EQ5. Effects/impact > Contribution analysis --\n\nThe programme contributed to…';
    const { section, body } = parseSectionBreadcrumb(text);
    expect(section).toBe('2. Evaluation findings > 2.5. EQ5. Effects/impact > Contribution analysis');
    expect(body).toBe('The programme contributed to…');
  });

  test('handles leading blank lines before the breadcrumb', () => {
    const { section, body } = parseSectionBreadcrumb('\n\n-- A > B --\nBody text.');
    expect(section).toBe('A > B');
    expect(body).toBe('Body text.');
  });

  test('leaves text without a breadcrumb untouched (no section)', () => {
    const { section, body } = parseSectionBreadcrumb('Just an ordinary excerpt with no heading line.');
    expect(section).toBeNull();
    expect(body).toBe('Just an ordinary excerpt with no heading line.');
  });

  test('a "-- … --" line without a " > " separator is not treated as a breadcrumb', () => {
    const text = '-- not a path --\nbody';
    const { section } = parseSectionBreadcrumb(text);
    expect(section).toBeNull();
  });
});
