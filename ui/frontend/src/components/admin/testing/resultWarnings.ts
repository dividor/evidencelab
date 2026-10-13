/**
 * Warnings the evaluation harness attached to a case's output — for example
 * the reranker was unavailable and the case was judged on unreranked results.
 * The case is still judged; the warning explains why its answer may differ
 * from what the app shows for the same query.
 */
export const resultWarnings = (output: unknown): string[] => {
  if (!output || typeof output !== 'object') return [];
  const raw = (output as Record<string, unknown>).warnings;
  if (!Array.isArray(raw)) return [];
  return raw.filter((w): w is string => typeof w === 'string' && w.trim() !== '');
};
