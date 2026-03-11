import { useCallback, useRef } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
import type { SearchResult } from '../types/api';

/**
 * Return a stable anonymous session ID (persisted in localStorage).
 * Used to correlate activity records for non-authenticated visitors.
 */
function getSessionId(): string {
  const KEY = 'evidencelab_session_id';
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}

/**
 * Hook for fire-and-forget logging of search activity.
 *
 * Works for both authenticated and anonymous users. Authenticated users
 * are identified by their JWT cookie; anonymous visitors are identified
 * by a random session_id stored in localStorage.
 *
 * Usage:
 *   const { logSearch, updateSummary } = useActivityLogging();
 *   // After search completes:
 *   logSearch(searchId, query, filters, results, { timing: { search_duration_ms: 123 } });
 *   // After AI summary stream finishes:
 *   updateSummary(searchId, summaryText, summaryDurationMs, drilldownTree);
 */
export function useActivityLogging() {
  // Track search IDs that have been logged so we don't double-log
  const loggedSearchIds = useRef(new Set<string>());

  /**
   * Log a search event. Called once after each search completes.
   * Sends rich result data (chunk_id, doc_id, title, score, page_num, chunk_text, link).
   * Optional `extra` object is shallow-merged into the `filters` field (e.g. timing data).
   */
  const logSearch = useCallback(
    (
      searchId: string,
      query: string,
      filters: Record<string, any> | null,
      results: SearchResult[],
      extra?: Record<string, any>,
      aiSummary?: string,
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

      const mergedFilters = {
        ...(filters && Object.keys(filters).length > 0 ? filters : {}),
        ...extra,
      };

      // Fire-and-forget — don't await, don't block
      axios
        .post(`${API_BASE_URL}/activity/`, {
          search_id: searchId,
          query,
          filters: Object.keys(mergedFilters).length > 0 ? mergedFilters : null,
          search_results: richResults,
          url: window.location.href,
          session_id: getSessionId(),
          ...(aiSummary ? { ai_summary: aiSummary } : {}),
        })
        .catch((err) => {
          // Silently fail — activity logging may be unavailable
          console.debug('Activity logging failed (non-critical):', err?.message);
        });
    },
    [],
  );

  /**
   * Update an existing activity record with summary, timing, or drilldown tree.
   * All fields are optional — send only what you want to update.
   * Called after the AI summary stream completes or when the drilldown tree changes.
   */
  const updateSummary = useCallback(
    (
      searchId: string,
      summaryText?: string,
      summaryDurationMs?: number,
      drilldownTree?: Record<string, any>,
    ) => {
      if (!searchId) return;
      // Must have at least one field to update
      if (!summaryText && summaryDurationMs == null && !drilldownTree) return;

      axios
        .patch(`${API_BASE_URL}/activity/${searchId}/summary`, {
          ...(summaryText ? { ai_summary: summaryText } : {}),
          ...(summaryDurationMs != null ? { summary_duration_ms: summaryDurationMs } : {}),
          ...(drilldownTree ? { drilldown_tree: drilldownTree } : {}),
          session_id: getSessionId(),
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
