import { useEffect, useMemo, useState } from 'react';
import type { SummaryModelConfig } from '../../../types/api';
import type { DocumentSummaryDefaults } from '../../../types/auth';
import { SavedSummary, fetchSummaryDefaults } from './documentSummaryApi';
import { SummaryConfigDefaults, SummarySettings, resolveSummarySettings } from './summarySettings';

/** What the Documents screen needs to let an administrator change summaries. */
export interface SummaryAdmin {
  dataSource: string;
  /** Config defaults with the team's group defaults applied. */
  defaults: SummarySettings;
  allSectionTypes: string[];
  model: SummaryModelConfig;
  onSaved: (saved: SavedSummary) => void;
}

interface UseSummaryAdminArgs {
  enabled: boolean;
  dataSource: string;
  groupDefaults?: DocumentSummaryDefaults | null;
  model?: SummaryModelConfig | null;
  onSaved: (saved: SavedSummary) => void;
}

/**
 * Loads the data source's summary defaults for an administrator. Returns
 * `admin: null` for everyone else, and an error message when the defaults
 * cannot be loaded or no summarization model is selected.
 */
export const useSummaryAdmin = ({
  enabled,
  dataSource,
  groupDefaults,
  model,
  onSaved,
}: UseSummaryAdminArgs): { admin: SummaryAdmin | null; error: string | null } => {
  const [config, setConfig] = useState<SummaryConfigDefaults | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !dataSource) return undefined;
    let cancelled = false;
    setLoadError(null);
    fetchSummaryDefaults(dataSource)
      .then((data) => {
        if (!cancelled) setConfig(data);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Summary settings could not be loaded, so summaries cannot be changed.');
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, dataSource]);

  const admin = useMemo<SummaryAdmin | null>(() => {
    if (!enabled || !config || !model) return null;
    return {
      dataSource,
      defaults: resolveSummarySettings(config, groupDefaults),
      allSectionTypes: config.all_section_types,
      model,
      onSaved,
    };
  }, [enabled, config, model, dataSource, groupDefaults, onSaved]);

  const error = !enabled ? null : loadError ?? (config && !model ? 'No summarization model is selected.' : null);
  return { admin, error };
};
