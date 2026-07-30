// Per-group feature-tab config: which main tabs are shown and their labels.
// Sourced from /users/me/effective-settings (`.tabs`, merged across the user's
// groups by the backend). Kept intentionally lightweight — it only controls tab
// visibility and labels, not behaviour.

export type TabKey = 'search' | 'assistant' | 'brief' | 'heatmap';

export const TAB_KEYS: TabKey[] = ['search', 'assistant', 'brief', 'heatmap'];

export const DEFAULT_TAB_LABELS: Record<TabKey, string> = {
  search: 'Search',
  assistant: 'Chat',
  brief: 'Brief',
  heatmap: 'Map',
};

// Short descriptions shown as hover/focus tooltips on each main nav tab.
// Keyed by the stable TabKey (not the label) so the copy stays correct even
// when a group overrides a tab's display label.
export const TAB_TOOLTIPS: Record<TabKey, string> = {
  search:
    'Find relevant evidence in evaluations and connect straight to the source document.',
  assistant: 'Ask questions in plain language and get cited answers.',
  brief: 'Turn any topic into a structured, fully cited brief.',
  heatmap:
    'Visualize evidence by theme, region, or year to quickly identify evidence coverage and gaps.',
};

export interface TabSetting {
  enabled?: boolean;
  label?: string | null;
}

export interface ResolvedTab {
  enabled: boolean;
  label: string;
}

export type TabsOverride = Partial<Record<TabKey, TabSetting>>;

/**
 * Resolve the effective per-tab config for the UI.
 *
 * `override` is the merged group setting (`effective-settings.tabs`). When it is
 * absent (no group configured tabs) every tab defaults to **enabled** with its
 * default label, preserving the stock behaviour. When present, a tab is shown
 * only if it is enabled, using its override label (or the default if blank).
 */
export function resolveTabs(
  override?: TabsOverride | null,
): Record<TabKey, ResolvedTab> {
  const out = {} as Record<TabKey, ResolvedTab>;
  for (const key of TAB_KEYS) {
    const entry = override ? override[key] : undefined;
    const label = (entry?.label || '').trim() || DEFAULT_TAB_LABELS[key];
    out[key] = { enabled: override ? Boolean(entry?.enabled) : true, label };
  }
  return out;
}
