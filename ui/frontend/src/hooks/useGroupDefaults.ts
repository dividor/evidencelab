/**
 * Custom hook to fetch and apply per-group search defaults.
 *
 * When a user is authenticated and belongs to groups with custom search_settings,
 * this hook fetches the merged effective settings from the backend and applies
 * any overrides that aren't already set via URL parameters.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
import type { SearchSettings } from '../types/auth';

/** URL parameter name → SearchSettings key mapping */
const SETTING_PARAM_MAP: Array<{ param: string; key: keyof SearchSettings }> = [
  { param: 'weight', key: 'denseWeight' },
  { param: 'rerank', key: 'rerank' },
  { param: 'recency', key: 'recencyBoost' },
  { param: 'recency_weight', key: 'recencyWeight' },
  { param: 'recency_scale', key: 'recencyScaleDays' },
  { param: 'sections', key: 'sectionTypes' },
  { param: 'keyword_boost', key: 'keywordBoostShortQueries' },
  { param: 'min_chunk_size', key: 'minChunkSize' },
  { param: 'highlight', key: 'semanticHighlighting' },
  { param: 'auto_min_score', key: 'autoMinScore' },
  { param: 'deduplicate', key: 'deduplicate' },
  { param: 'field_boost', key: 'fieldBoost' },
  { param: 'field_boost_fields', key: 'fieldBoostFields' },
];

interface AuthState {
  isLoading: boolean;
  isAuthenticated: boolean;
  user: unknown;
}

type Setters = Record<keyof SearchSettings, (value: any) => void>;

/**
 * Apply group defaults to state setters for keys not present in URL params.
 */
function applyGroupDefaults(defaults: SearchSettings, setters: Setters): void {
  const params = new URLSearchParams(window.location.search);
  for (const { param, key } of SETTING_PARAM_MAP) {
    const value = defaults[key];
    if (!params.has(param) && value !== undefined) {
      setters[key](value);
    }
  }
}

export function useGroupDefaults(
  userModuleEnabled: boolean,
  authState: AuthState,
  setters: Setters,
): SearchSettings | undefined {
  const [groupDefaults, setGroupDefaults] = useState<SearchSettings | undefined>(undefined);
  const loadedRef = useRef(false);

  // Fetch effective settings when user logs in
  useEffect(() => {
    if (!userModuleEnabled || authState.isLoading) return;
    if (!authState.isAuthenticated || !authState.user) {
      if (loadedRef.current) {
        setGroupDefaults(undefined);
        loadedRef.current = false;
      }
      return;
    }
    if (loadedRef.current) return;

    (async () => {
      try {
        const resp = await axios.get<SearchSettings>(`${API_BASE_URL}/users/me/effective-settings`);
        const settings = resp.data;
        if (settings && Object.keys(settings).length > 0) {
          setGroupDefaults(settings);
        }
      } catch {
        // Non-critical — system defaults apply
      }
      loadedRef.current = true;
    })();
  }, [userModuleEnabled, authState.isLoading, authState.isAuthenticated, authState.user]);

  // Apply defaults when they arrive (only for settings not in URL)
  useEffect(() => {
    if (!groupDefaults || Object.keys(groupDefaults).length === 0) return;
    applyGroupDefaults(groupDefaults, setters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupDefaults]);

  return groupDefaults;
}
