import { buildSearchURL } from '../utils/searchUrl';

const NO_SETTINGS = Array(16).fill(undefined) as [
  number?, boolean?, boolean?, number?, number?, string[]?, boolean?, number?, boolean?, boolean?, boolean?,
  (string | null)?, (string | null)?, (string | null)?, boolean?, Record<string, number>?,
];

describe('buildSearchURL wide search params', () => {
  test('omits wide params when off and at defaults', () => {
    const url = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, false, 5, 20));
    expect(url.has('wide')).toBe(false);
    expect(url.has('wide_group_size')).toBe(false);
    expect(url.has('wide_limit')).toBe(false);
  });

  test('writes wide=true and non-default sizes', () => {
    const url = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, true, 3, 40));
    expect(url.get('wide')).toBe('true');
    expect(url.get('wide_group_size')).toBe('3');
    expect(url.get('wide_limit')).toBe('40');
  });
});
