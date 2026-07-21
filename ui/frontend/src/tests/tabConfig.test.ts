import {
  DEFAULT_TAB_LABELS,
  TAB_KEYS,
  resolveTabs,
} from '../components/layout/tabConfig';

describe('resolveTabs', () => {
  it('defaults every tab to enabled with its default label when no override', () => {
    const r = resolveTabs(undefined);
    TAB_KEYS.forEach((k) => {
      expect(r[k].enabled).toBe(true);
      expect(r[k].label).toBe(DEFAULT_TAB_LABELS[k]);
    });
  });

  it('respects per-tab enabled flags from the override', () => {
    const r = resolveTabs({
      search: { enabled: true },
      assistant: { enabled: false },
      brief: { enabled: true },
      heatmap: { enabled: false },
    });
    expect(r.search.enabled).toBe(true);
    expect(r.assistant.enabled).toBe(false);
    expect(r.brief.enabled).toBe(true);
    expect(r.heatmap.enabled).toBe(false);
  });

  it('uses the override label when set and the default when blank', () => {
    const r = resolveTabs({
      brief: { enabled: true, label: 'Briefings' },
      search: { enabled: true, label: '   ' },
    });
    expect(r.brief.label).toBe('Briefings');
    expect(r.search.label).toBe(DEFAULT_TAB_LABELS.search);
  });

  it('treats a present override as authoritative: a missing tab is disabled', () => {
    const r = resolveTabs({ search: { enabled: true } });
    expect(r.search.enabled).toBe(true);
    expect(r.assistant.enabled).toBe(false);
  });
});
