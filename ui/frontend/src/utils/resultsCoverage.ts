// Builds the human-readable explanation of what the organization result
// counts (e.g. "WFP (28)") actually represent: the distinct documents behind
// the most relevant text excerpts returned for the query. The numbers are
// derived from live search state (never hardcoded) so the sentence stays true
// regardless of the configured page size.

export interface ResultsCoverage {
  /** Relevant text excerpts (chunks) currently backing the result chips. */
  excerptCount: number;
  /** Distinct source documents those excerpts come from. */
  documentCount: number;
  /** Distinct organizations across those documents. */
  orgCount: number;
}

/** Pluralize a count with its noun: `plural(1, 'document') -> '1 document'`. */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * Compose the coverage explanation shown in the results info tooltip.
 *
 * Example (28 docs, 1 org, 50 excerpts):
 *   "The 50 most relevant text excerpts for your query come from 28
 *    documents. Expecting broader or narrower coverage? Refine your search
 *    query or adjust the filters on the left."
 */
export function buildResultsCoverageText({
  excerptCount,
  documentCount,
  orgCount,
}: ResultsCoverage): string {
  const orgClause = orgCount > 1 ? ` across ${plural(orgCount, 'organization')}` : '';
  return (
    `The ${plural(excerptCount, 'most relevant text excerpt')} for your query ` +
    `come from ${plural(documentCount, 'document')}${orgClause}. ` +
    'Expecting broader or narrower coverage? Refine your search query or ' +
    'adjust the filters on the left.'
  );
}
