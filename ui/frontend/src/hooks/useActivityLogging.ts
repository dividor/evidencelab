import { useCallback, useRef } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
import type { SearchResult } from '../types/api';

/**
 * Hook for fire-and-forget logging of search activity.
 *
 * Usage:
 *   const { logSearch, updateSummary } = useActivityLogging();
 *   // After search completes:
 *   logSearch(searchId, query, filters, results);
 *   // After AI summary stream finishes:
 *   updateSummary(searchId, summaryText);
 */
export function useActivityLogging() {
  // Track search IDs that have been logged so we don't double-log
  const loggedSearchIds = useRef(new Set<string>());

  /**
   * Log a search event. Called once after each search completes.
   * Sends rich result data (chunk_id, doc_id, title, score, page_num, chunk_text, link).
   */
  const logSearch = useCallback(
    (
      searchId: string,
      query: string,
      filters: Record<string, any> | null,
      results: SearchResult[],
    ) => {
      if (loggedSearchIds.current.has(searchId)) return;
      loggedSearchIds.current.add(searchId);

      // Include rich result data (same fields as rating context) for admin visibility
      const richResults = results.slice(0, 50).map((r) => ({
        chunk_id: r.chunk_id,
        doc_id: r.doc_id,
        title: r.title,
        score: r.score,
        page_num: r.page_num || null,
        chunk_text: r.text || '',
        link: r.link || '',
      }));

      // Fire-and-forget — don't await, don't block
      axios
        .post(`${API_BASE_URL}/activity/`, {
          search_id: searchId,
          query,
          filters: filters && Object.keys(filters).length > 0 ? filters : null,
          search_results: richResults,
          url: window.location.href,
        })
        .catch((err) => {
          // Silently fail — user may not be authenticated or activity logging may be unavailable
          console.debug('Activity logging failed (non-critical):', err?.message);
        });
    },
    [],
  );

  /**
   * Append / update the AI summary text on a previously logged activity record.
   * Called after the AI summary stream completes.
   */
  const updateSummary = useCallback(
    (searchId: string, summaryText: string) => {
      if (!summaryText || !searchId) return;

      axios
        .patch(`${API_BASE_URL}/activity/${searchId}/summary`, {
          ai_summary: summaryText,
        })
        .catch((err) => {
          console.debug('Activity summary update failed (non-critical):', err?.message);
        });
    },
    [],
  );

  return { logSearch, updateSummary };
}

export default useActivityLogging;
