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

/** How many more documents matched the query beyond those on the page. */
export function approximateExtraDocuments(coverage: SearchCoverage): number {
  return approximateCount(
    Math.max(coverage.candidate_documents - coverage.documents_in_results, 0),
  );
}

/**
 * Approximate total of matching documents, for the broadened-state copy
 * ("36 of about 170 matching documents"). Never less than the number of
 * documents actually on the page.
 */
export function approximateMatchingDocuments(coverage: SearchCoverage): number {
  return Math.max(
    approximateCount(coverage.candidate_documents),
    coverage.documents_in_results,
  );
}
