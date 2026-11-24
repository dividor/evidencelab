import { buildSearchURL, getSearchStateFromURL, DEFAULT_SECTION_TYPES } from '../utils/searchUrl';
import { joinFilterValues } from '../utils/filterValues';

const SDG16 = 'SDG16 - Peace, Justice and Strong Institutions';
const SDG9 = 'SDG9 - Industry, Innovation and Infrastructure';

// Regression: a Search link with SDG9/SDG16 selected came back as four broken
// selections, because the filter string was split on every comma.
describe('search links with filter values that contain commas', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  test('reading a link keeps each escaped value whole', () => {
    const params = new URLSearchParams({ q: 'food', tag_sdg: joinFilterValues([SDG9, SDG16]) });
    window.history.replaceState(null, '', `/?${params.toString()}`);
    const state = getSearchStateFromURL(['tag_sdg', 'country'], DEFAULT_SECTION_TYPES);
    expect(state.selectedFilters.tag_sdg).toEqual([SDG9, SDG16]);
    expect(state.selectedFilters.country).toEqual([]);
  });

  test('a plain comma list in an older link still reads as separate values', () => {
    window.history.replaceState(null, '', '/?q=food&country=Kenya,Uganda');
    const state = getSearchStateFromURL(['country'], DEFAULT_SECTION_TYPES);
    expect(state.selectedFilters.country).toEqual(['Kenya', 'Uganda']);
  });

  test('the filter string is sent to the API unchanged, escapes included', () => {
    const filter = joinFilterValues([SDG16]);
    const url = new URLSearchParams(buildSearchURL('food', { tag_sdg: filter }));
    expect(url.get('tag_sdg')).toBe('SDG16 - Peace\\, Justice and Strong Institutions');
  });
});
