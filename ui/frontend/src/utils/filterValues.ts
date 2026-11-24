/**
 * Multi-select filter values in one string, as the API reads them.
 *
 * Values are separated by commas. A comma inside a value is written `\,` and a
 * backslash `\\`, so names such as "SDG16 - Peace, Justice and Strong
 * Institutions" travel whole (the API parser is `parse_filter_values` in
 * `ui/backend/utils/filter_helpers.py`). Values without commas or backslashes
 * read exactly as plain comma lists, so older links keep working.
 */

const SEPARATOR = ',';
const ESCAPE = '\\';

/** Escape one value so it can sit in a comma-separated filter string. */
export const escapeFilterValue = (value: string): string =>
  value.split(ESCAPE).join(`${ESCAPE}${ESCAPE}`).split(SEPARATOR).join(`${ESCAPE}${SEPARATOR}`);

/** Join selected values into one filter string (empty string for none). */
export const joinFilterValues = (values: string[]): string =>
  values.map(escapeFilterValue).join(SEPARATOR);

/** Split a filter string into its values, undoing the escaping. */
export const splitFilterValues = (text: string | null | undefined): string[] => {
  if (!text) return [];
  const values: string[] = [];
  let current = '';
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const following = text[index + 1];
    if (char === ESCAPE && (following === SEPARATOR || following === ESCAPE)) {
      current += following;
      index += 1;
    } else if (char === SEPARATOR) {
      values.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  values.push(current);
  return values.map((value) => value.trim()).filter((value) => value.length > 0);
};

/**
 * Each filter field's selected values, for records people read (the Activity
 * log), so a value shows as selected rather than with its escapes.
 */
export const filterValuesByField = (
  filters: Record<string, string | undefined>
): Record<string, string[]> =>
  Object.fromEntries(
    Object.entries(filters)
      .map(([field, value]) => [field, splitFilterValues(value)] as [string, string[]])
      .filter(([, values]) => values.length > 0)
  );
