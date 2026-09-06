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
