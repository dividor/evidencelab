/**
 * Shared helpers for parsing and numbering inline citations (e.g. `[1]`, `[2, 5]`)
 * in AI summary text.
 *
 * Both the on-screen summary (`AiSummaryWithCitations`, `AiSummaryReferences`) and
 * the export (`exportResearch`) must renumber citations identically, otherwise the
 * same summary shows different reference numbers on screen versus in the downloaded
 * document. Keeping the numbering logic in one place guarantees they cannot drift.
 *
 * A citation number `[N]` is a 1-based index into the result array that was sent to
 * the LLM. Callers are responsible for resolving `N` against that same array.
 */

/** Source pattern for an inline citation marker such as `[1]` or `[2, 5]`. */
export const CITATION_PATTERN = '\\[(\\d+(?:,\\s*\\d+)*)\\]';

/**
 * Create a fresh global `RegExp` for matching citation markers.
 *
 * A new instance is returned on every call so that callers using `.exec()` do not
 * share mutable `lastIndex` state across modules.
 */
export const createCitationRegex = (): RegExp => new RegExp(CITATION_PATTERN, 'g');

/** Parse the inner numbers of a citation marker, e.g. `"2, 5"` -> `[2, 5]`. */
export const parseCitationNumbers = (rawNumbers: string): number[] =>
  rawNumbers.split(',').map((item) => parseInt(item.trim(), 10));

/** Extract every unique citation number from summary text, sorted ascending. */
export const extractCitedNumbers = (summaryText: string): number[] => {
  const cited = new Set<number>();
  const regex = createCitationRegex();
  let match: RegExpExecArray | null;
  while ((match = regex.exec(summaryText)) !== null) {
    parseCitationNumbers(match[1]).forEach((num) => cited.add(num));
  }
  return Array.from(cited).sort((a, b) => a - b);
};

/**
 * Build a map from each original citation number to its sequential (1-based) display
 * number, ordered by ascending original number.
 *
 * This is the single source of truth for citation numbering, shared by the on-screen
 * summary and the export.
 */
export const buildCitationSequenceMap = (summaryText: string): Map<number, number> => {
  const map = new Map<number, number>();
  extractCitedNumbers(summaryText).forEach((origNum, idx) => {
    map.set(origNum, idx + 1);
  });
  return map;
};
