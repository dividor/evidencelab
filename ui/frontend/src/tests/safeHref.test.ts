import { safeHref } from '../utils/safeHref';

describe('safeHref', () => {
  test.each([
    ['https://example.org/report.pdf', 'https://example.org/report.pdf'],
    ['http://example.org/a', 'http://example.org/a'],
    ['  https://example.org/b  ', 'https://example.org/b'],
    ['mailto:someone@example.org', 'mailto:someone@example.org'],
    ['/api/pdf/123?data_source=uneg', '/api/pdf/123?data_source=uneg'],
  ])('keeps a normal link %s', (input, expected) => {
    expect(safeHref(input)).toBe(expected);
  });

  test.each([
    'javascript:alert(1)',
    ' JaVaScRiPt:alert(1)',
    'java\tscript:alert(1)',
    'vbscript:msgbox(1)',
    'data:text/html;base64,PHNjcmlwdD4=',
    'file:///etc/passwd',
    '//evil.example.org/x',
    '/\\evil.example.org',
    'not a url',
    '',
  ])('refuses %s', (input) => {
    expect(safeHref(input)).toBeUndefined();
  });

  test('refuses null and undefined', () => {
    expect(safeHref(null)).toBeUndefined();
    expect(safeHref(undefined)).toBeUndefined();
  });
});
