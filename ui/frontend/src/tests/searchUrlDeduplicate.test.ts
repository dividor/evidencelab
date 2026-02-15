import { buildSearchURL, getSearchStateFromURL, DEFAULT_SECTION_TYPES } from '../utils/searchUrl';

describe('searchUrl deduplicate support', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
    });
  });

  const setURL = (search: string) => {
    Object.defineProperty(window, 'location', {
      value: { ...originalLocation, search },
      writable: true,
    });
  };

  describe('getSearchStateFromURL', () => {
    test('defaults deduplicate to true when not in URL', () => {
      setURL('?q=test');
      const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES);
      expect(state.deduplicate).toBe(true);
    });

    test('parses deduplicate=false from URL', () => {
      setURL('?q=test&deduplicate=false');
      const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES);
      expect(state.deduplicate).toBe(false);
    });

    test('parses deduplicate=true from URL', () => {
      setURL('?q=test&deduplicate=true');
      const state = getSearchStateFromURL([], DEFAULT_SECTION_TYPES);
      expect(state.deduplicate).toBe(true);
    });
  });

  describe('buildSearchURL', () => {
    test('omits deduplicate when true (default)', () => {
      const url = buildSearchURL('test', {}, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, true);
      expect(url).not.toContain('deduplicate');
    });

    test('includes deduplicate=false when disabled', () => {
      const url = buildSearchURL('test', {}, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, false);
      expect(url).toContain('deduplicate=false');
    });

    test('omits deduplicate when undefined', () => {
      const url = buildSearchURL('test', {});
      expect(url).not.toContain('deduplicate');
    });
  });
});
