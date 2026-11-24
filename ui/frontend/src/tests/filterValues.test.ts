import {
  escapeFilterValue,
  filterValuesByField,
  joinFilterValues,
  splitFilterValues,
} from '../utils/filterValues';

const SDG16 = 'SDG16 - Peace, Justice and Strong Institutions';
const SDG9 = 'SDG9 - Industry, Innovation and Infrastructure';

describe('filter value strings', () => {
  test('a value with a comma is escaped so it stays whole', () => {
    expect(escapeFilterValue(SDG16)).toBe('SDG16 - Peace\\, Justice and Strong Institutions');
  });

  test('a backslash is escaped before commas', () => {
    expect(escapeFilterValue('a\\b,c')).toBe('a\\\\b\\,c');
  });

  test('values without commas or backslashes join as a plain comma list', () => {
    expect(joinFilterValues(['Kenya', 'Uganda'])).toBe('Kenya,Uganda');
    expect(joinFilterValues([])).toBe('');
  });

  test('join then split gives back the same values', () => {
    const values = [SDG9, SDG16, 'C:\\docs', 'a\\,b', 'Plain'];
    expect(splitFilterValues(joinFilterValues(values))).toEqual(values);
  });

  test('a plain comma list splits as before, trimming and dropping blanks', () => {
    expect(splitFilterValues(' Kenya, Uganda ,, ')).toEqual(['Kenya', 'Uganda']);
  });

  test('a lone backslash is kept as written', () => {
    expect(splitFilterValues('C:\\docs')).toEqual(['C:\\docs']);
  });

  test('empty input gives no values', () => {
    expect(splitFilterValues('')).toEqual([]);
    expect(splitFilterValues(null)).toEqual([]);
    expect(splitFilterValues(undefined)).toEqual([]);
  });

  test('filters are read into each field\'s selected values, empty fields dropped', () => {
    expect(
      filterValuesByField({
        tag_sdg: joinFilterValues([SDG9, SDG16]),
        country: 'Kenya',
        published_year_min: '2020',
        organization: undefined,
        region: '',
      })
    ).toEqual({ tag_sdg: [SDG9, SDG16], country: ['Kenya'], published_year_min: ['2020'] });
  });
});
