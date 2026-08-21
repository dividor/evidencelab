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
 * Round document counts to the nearest ten once large enough that exact
 * figures would suggest false precision (the candidate pool is a sample,
 * not a census).
 */
function approximateCount(count: number): number {
  return count >= 20 ? Math.round(count / 10) * 10 : count;
}

/**
 * Approximate total of matching documents. Both CoverageNotice states quote
 * this same figure ("N of about 170 matching documents") so the numbers stay
 * consistent across the alert and the broadened view. Never less than the
 * number of documents actually on the page.
 */
export function approximateMatchingDocuments(coverage: SearchCoverage): number {
  return Math.max(
    approximateCount(coverage.candidate_documents),
    coverage.documents_in_results,
  );
}
