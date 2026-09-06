import type { SearchResult } from '../types/api';

/** Default cap on the results the AI summary is built from (a user or team setting). */
export const SUMMARY_RESULT_LIMIT = 20;

/**
 * Pick the results the AI summary (and a drill-down node) is built from.
 *
 * Plain search: the top `limit` results, as ranked.
 *
 * Wide search returns results document by document (all of the first
 * document's excerpts, then the second's, …), so the first `limit` of them
 * cover only the first few documents. In wide mode spread the selection
 * across documents instead: the best excerpt of each document in document
 * order, then each document's second excerpt, and so on, until `limit`. The
 * summary then cites as many documents as the limit allows, which is the
 * point of wide search.
 *
 * A `limit` of null means no cap: every result is used.
 */
export const selectSummaryResults = (
  results: SearchResult[],
  spreadAcrossDocuments: boolean,
  limit: number | null = SUMMARY_RESULT_LIMIT,
): SearchResult[] => {
  const cap = limit === null ? results.length : limit;
  if (!spreadAcrossDocuments) {
    return results.slice(0, cap);
  }
  const byDocument = new Map<string, SearchResult[]>();
  for (const result of results) {
    const key = result.doc_id || result.chunk_id;
    const bucket = byDocument.get(key);
    if (bucket) {
      bucket.push(result);
    } else {
      byDocument.set(key, [result]);
    }
  }
  const queues = Array.from(byDocument.values());
  const selected: SearchResult[] = [];
  for (let round = 0; selected.length < cap; round++) {
    let addedThisRound = false;
    for (const queue of queues) {
      if (round < queue.length && selected.length < cap) {
        selected.push(queue[round]);
        addedThisRound = true;
      }
    }
    if (!addedThisRound) break;
  }
  return selected;
};
