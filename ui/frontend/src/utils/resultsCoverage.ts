// Helpers for communicating how the returned results page relates to the
// wider corpus (see CoverageNotice). The numbers are derived from the live
// search response (never hardcoded) so the copy stays true regardless of
// the configured page size.

import type { SearchCoverage } from '../types/api';

/** Pluralize a count with its noun: `plural(1, 'document') -> '1 document'`. */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * How many more documents matched the query beyond those on the page,
 * rounded to the nearest ten once large enough that exact figures would
 * suggest false precision (the candidate pool is a sample, not a census).
 */
export function approximateExtraDocuments(coverage: SearchCoverage): number {
  const extra = Math.max(
    coverage.candidate_documents - coverage.documents_in_results,
    0,
  );
  return extra >= 20 ? Math.round(extra / 10) * 10 : extra;
}
