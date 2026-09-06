import { buildSearchURL, DEFAULT_SECTION_TYPES, getSearchStateFromURL, SYSTEM_DEFAULTS } from '../utils/searchUrl';

// getSearchStateFromURL reads window.location.search
const readState = (search: string, groupDefaults?: { groupByDocument?: boolean }) => {
  window.history.replaceState(null, '', `/${search}`);
  return getSearchStateFromURL([], DEFAULT_SECTION_TYPES, groupDefaults);
};

const NO_SETTINGS = Array(16).fill(undefined) as [
  number?, boolean?, boolean?, number?, number?, string[]?, boolean?, number?, boolean?, boolean?, boolean?,
  (string | null)?, (string | null)?, (string | null)?, boolean?, Record<string, number>?,
];
// wideSearch, wideGroupSize, wideLimit, summaryLimitResults, summaryMaxResults, summaryTemperature
const WIDE_AND_SUMMARY_DEFAULTS = [false, 5, 20, true, 20, 0] as const;

describe('group by document URL state', () => {
  test('defaults to off', () => {
    expect(SYSTEM_DEFAULTS.groupByDocument).toBe(false);
    expect(readState('?q=x').groupByDocument).toBe(false);
  });

  test('reads group_by_doc from the URL', () => {
    expect(readState('?q=x&group_by_doc=true').groupByDocument).toBe(true);
    expect(readState('?q=x&group_by_doc=false').groupByDocument).toBe(false);
  });

  test('a team default applies when the URL is silent, and the URL wins otherwise', () => {
    expect(readState('?q=x', { groupByDocument: true }).groupByDocument).toBe(true);
    expect(readState('?q=x&group_by_doc=false', { groupByDocument: true }).groupByDocument).toBe(false);
  });

  test('buildSearchURL writes group_by_doc only when on', () => {
    const off = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, ...WIDE_AND_SUMMARY_DEFAULTS, false));
    expect(off.has('group_by_doc')).toBe(false);
    const on = new URLSearchParams(buildSearchURL('q', {}, ...NO_SETTINGS, ...WIDE_AND_SUMMARY_DEFAULTS, true));
    expect(on.get('group_by_doc')).toBe('true');
  });
});
