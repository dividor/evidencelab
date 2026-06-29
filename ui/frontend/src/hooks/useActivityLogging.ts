import { useCallback, useRef } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
import type { SearchResult } from '../types/api';

/**
 * LLM usage payload threaded into activity log POST/PATCH calls.
 *
 * Fields are optional because providers vary in what they report. The
 * backend recomputes `cost_usd` from `llm_model` + token counts so the
 * cost cannot be tampered with from the client.
 */
export interface ActivityUsage {
  llm_model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

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
      usage?: ActivityUsage,
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
          ...(usage || {}),
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
      usage?: ActivityUsage,
    ) => {
      if (!searchId) return;
      const hasUsage = !!usage && Object.keys(usage).length > 0;
      // Must have at least one field to update
      if (!summaryText && summaryDurationMs == null && !drilldownTree && !hasUsage) return;

      axios
        .patch(`${API_BASE_URL}/activity/${searchId}/summary`, {
          ...(summaryText ? { ai_summary: summaryText } : {}),
          ...(summaryDurationMs != null ? { summary_duration_ms: summaryDurationMs } : {}),
          ...(drilldownTree ? { drilldown_tree: drilldownTree } : {}),
          ...(usage || {}),
          session_id: getSessionId(),
        })
        .catch((err) => {
          console.debug('Activity summary update failed (non-critical):', err?.message);
        });
    },
    [],
  );

  /**
   * Upsert a Brief activity record (type "brief"). Unlike logSearch this does
   * NOT dedupe — it is called on each brief save with a stable activityId so
   * the backend (which upserts by search_id) keeps a single activity row per
   * brief, refreshed with the latest title, prose and cited sources.
   */
  const logBrief = useCallback(
    (
      activityId: string,
      title: string,
      summaryMarkdown: string,
      sources: Array<{
        chunkId?: string;
        docId?: string;
        title?: string;
        score?: number;
        page?: number;
        text?: string;
      }>,
    ) => {
      if (!activityId) return;
      const richResults = (sources || []).slice(0, 50).map((s) => ({
        chunk_id: s.chunkId || '',
        doc_id: s.docId || '',
        title: s.title || '',
        score: s.score || 0,
        page_num: s.page || null,
        chunk_text: s.text || '',
        link: '',
      }));

      axios
        .post(`${API_BASE_URL}/activity/`, {
          search_id: activityId,
          query: title,
          filters: { type: 'brief' },
          search_results: richResults,
          url: window.location.href,
          session_id: getSessionId(),
          ...(summaryMarkdown ? { ai_summary: summaryMarkdown } : {}),
        })
        .catch((err) => {
          console.debug('Brief activity logging failed (non-critical):', err?.message);
        });
    },
    [],
  );

  return { logSearch, updateSummary, logBrief };
}

export default useActivityLogging;
