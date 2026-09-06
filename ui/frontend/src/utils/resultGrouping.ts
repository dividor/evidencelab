import type { SearchResult } from '../types/api';

export interface DocumentResultGroup {
  docId: string;
  /** Excerpts from this document, in their search-ranked order. */
  results: SearchResult[];
}

/**
 * Group results by document, keeping the order in which each document first
 * appears in the ranked list (so documents are ordered by their best match)
 * and the ranked order of excerpts within each document.
 */
export const groupResultsByDocument = (results: SearchResult[]): DocumentResultGroup[] => {
  const groups = new Map<string, DocumentResultGroup>();
  results.forEach((result) => {
    const docId = result.doc_id || result.chunk_id;
    const group = groups.get(docId);
    if (group) {
      group.results.push(result);
    } else {
      groups.set(docId, { docId, results: [result] });
    }
  });
  return Array.from(groups.values());
};

export type GroupSortBy = 'relevance' | 'date';

/** Cumulative relevance of a document: the sum of its excerpts' scores. */
export const groupRelevance = (group: DocumentResultGroup): number =>
  group.results.reduce((sum, result) => sum + (result.score || 0), 0);

/** Publication year of a document as a number, or null when it has none. */
export const documentYear = (result: SearchResult): number | null => {
  const raw = result.year || result.metadata?.year;
  const year = Number.parseInt(String(raw ?? ''), 10);
  return Number.isFinite(year) ? year : null;
};

/**
 * Order document groups for display. Relevance: cumulative relevance, highest
 * first. Date: publication year, newest first, undated documents last. Both
 * are stable, so ties keep the search-ranked order.
 */
export const sortDocumentGroups = (
  groups: DocumentResultGroup[],
  sortBy: GroupSortBy,
): DocumentResultGroup[] => {
  const indexed = groups.map((group, index) => ({ group, index }));
  const compare =
    sortBy === 'date'
      ? (a: DocumentResultGroup, b: DocumentResultGroup) => {
          const ya = documentYear(a.results[0]);
          const yb = documentYear(b.results[0]);
          if (ya === yb) return 0;
          if (ya === null) return 1;
          if (yb === null) return -1;
          return yb - ya;
        }
      : (a: DocumentResultGroup, b: DocumentResultGroup) => groupRelevance(b) - groupRelevance(a);
  indexed.sort((a, b) => compare(a.group, b.group) || a.index - b.index);
  return indexed.map(({ group }) => group);
};
