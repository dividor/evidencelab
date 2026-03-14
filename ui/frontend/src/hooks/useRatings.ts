import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

export interface Rating {
  id: string;
  user_id: string | null;
  rating_type: string;
  reference_id: string;
  item_id: string | null;
  score: number;
  comment: string | null;
  context: Record<string, any> | null;
  url: string | null;
  created_at: string;
  updated_at: string;
}

interface UseRatingsOptions {
  /** Filter by rating type (e.g., 'search_result', 'ai_summary', 'doc_summary', 'taxonomy') */
  ratingType?: string;
  /** Filter by reference ID (e.g., search_id, doc_id) */
  referenceId?: string;
  /** Whether to fetch immediately on mount / prop change */
  enabled?: boolean;
}

interface UseRatingsReturn {
  /** Map of item_id (or '') → Rating for quick lookup */
  ratings: Map<string, Rating>;
  /** Whether a fetch is in progress */
  loading: boolean;
  /** Submit (create / update) a rating; returns the saved Rating */
  submitRating: (params: {
    ratingType: string;
    referenceId: string;
    itemId?: string;
    score: number;
    comment?: string;
    context?: Record<string, any>;
  }) => Promise<Rating>;
  /** Delete a rating by id */
  deleteRating: (ratingId: string) => Promise<void>;
  /** Manually re-fetch */
  refresh: () => Promise<void>;
}

/**
 * Hook to manage the current user's ratings for a given type / reference.
 */
export function useRatings({
  ratingType,
  referenceId,
  enabled = true,
}: UseRatingsOptions = {}): UseRatingsReturn {
  const [ratings, setRatings] = useState<Map<string, Rating>>(new Map());
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchRatings = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (ratingType) params.rating_type = ratingType;
      if (referenceId) params.reference_id = referenceId;
      const resp = await axios.get<Rating[]>(`${API_BASE_URL}/ratings/mine`, { params });
      if (!mountedRef.current) return;
      const map = new Map<string, Rating>();
      for (const r of resp.data) {
        map.set(r.item_id || '', r);
      }
      setRatings(map);
    } catch {
      // Silently fail — user may not be authenticated
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [ratingType, referenceId, enabled]);

  useEffect(() => {
    fetchRatings();
  }, [fetchRatings]);

  const submitRating = useCallback(
    async (params: {
      ratingType: string;
      referenceId: string;
      itemId?: string;
      score: number;
      comment?: string;
      context?: Record<string, any>;
    }): Promise<Rating> => {
      const resp = await axios.post<Rating>(`${API_BASE_URL}/ratings/`, {
        rating_type: params.ratingType,
        reference_id: params.referenceId,
        item_id: params.itemId || null,
        score: params.score,
        comment: params.comment || null,
        context: params.context || null,
        url: window.location.href,
      });
      const saved = resp.data;
      if (mountedRef.current) {
        setRatings((prev) => {
          const next = new Map(prev);
          next.set(saved.item_id || '', saved);
          return next;
        });
      }
      return saved;
    },
    []
  );

  const deleteRating = useCallback(async (ratingId: string) => {
    await axios.delete(`${API_BASE_URL}/ratings/${ratingId}`);
    if (mountedRef.current) {
      setRatings((prev) => {
        const next = new Map(prev);
        // Find and remove by id
        for (const [key, r] of next) {
          if (r.id === ratingId) {
            next.delete(key);
            break;
          }
        }
        return next;
      });
    }
  }, []);

  return {
    ratings,
    loading,
    submitRating,
    deleteRating,
    refresh: fetchRatings,
  };
}

export default useRatings;
