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

  test('omits summary cap params at defaults and writes them when changed', () => {
    const atDefaults = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, false, 5, 20, true, 20));
    expect(atDefaults.has('summary_limit')).toBe(false);
    expect(atDefaults.has('summary_max')).toBe(false);
    const changed = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, false, 5, 20, false, 35));
    expect(changed.get('summary_limit')).toBe('false');
    expect(changed.get('summary_max')).toBe('35');
  });

  test('writes the summary temperature only when it is not the default', () => {
    expect(new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, false, 5, 20, true, 20, 0)).has('summary_temp')).toBe(false);
    expect(new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, false, 5, 20, true, 20, 0.7)).get('summary_temp')).toBe('0.7');
  });

  test('writes wide=true and non-default sizes', () => {
    const url = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, true, 3, 40));
    expect(url.get('wide')).toBe('true');
    expect(url.get('wide_group_size')).toBe('3');
    expect(url.get('wide_limit')).toBe('40');
  });
});
