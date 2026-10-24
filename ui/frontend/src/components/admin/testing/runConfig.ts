/**
 * Presentation of a run's stored configuration (`test_runs.config`): the
 * models, group and search/summary settings the harness actually ran with.
 * Rows are grouped into sections and each value is compared with the previous
 * run so what changed between runs is visible at a glance.
 */

export type RunConfig = Record<string, unknown>;

export interface RunConfigRow {
  section: string;
  key: string;
  label: string;
  value: string;
  /** The previous run recorded a different value for this key. */
  changed: boolean;
}

type Formatter = (value: unknown, config: RunConfig) => string;

const onOff: Formatter = (v) => (v === true ? 'on' : v === false ? 'off' : plain(v));

const plain = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '—';
  if (Array.isArray(v)) return v.map(String).join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const promptSummary: Formatter = (v) =>
  typeof v === 'string' && v.trim() ? `group prompt (${v.length} chars)` : 'default';

const rerankCap = (v: unknown): string => (typeof v === 'number' && v > 0 ? String(v) : 'all');

const SECTIONS: Array<{ section: string; rows: Array<[string, string, Formatter?]> }> = [
  {
    section: 'Models',
    rows: [
      ['model_combo', 'Model combo'],
      ['embedding_model', 'Embedding model'],
      ['summary_model', 'Summary model'],
      ['judge_model', 'Judge model'],
      ['rerank_model', 'Reranker'],
      ['max_rerank_candidates', 'Rerank candidates', rerankCap],
      ['max_tokens', 'Summary max tokens'],
    ],
  },
  {
    section: 'Group',
    rows: [
      ['group_name', 'Run as group'],
      ['summary_prompt', 'Summary prompt', promptSummary],
    ],
  },
  {
    section: 'Search',
    rows: [
      ['rerank', 'Rerank', onOff],
      ['dense_weight', 'Dense weight'],
      ['min_chunk_size', 'Min chunk size'],
      ['section_types', 'Section types'],
      ['field_boost', 'Field boost', onOff],
      ['field_boost_fields', 'Field boost fields'],
      ['deduplicate', 'Deduplicate', onOff],
      ['auto_min_score', 'Auto min score', onOff],
      ['keyword_boost_short_queries', 'Keyword boost (short queries)', onOff],
      ['recency_boost', 'Recency boost', onOff],
      ['recency_weight', 'Recency weight'],
      ['recency_scale_days', 'Recency scale (days)'],
      ['wide_search', 'Wide search', onOff],
      ['wide_group_size', 'Wide group size'],
      ['wide_limit', 'Wide limit'],
      ['limit', 'Result limit'],
    ],
  },
  {
    section: 'Summary',
    rows: [
      ['summary_limit_results', 'Cap results', onOff],
      ['max_results', 'Max results'],
      ['temperature', 'Temperature'],
    ],
  },
];

const KNOWN_KEYS = new Set(SECTIONS.flatMap((s) => s.rows.map(([key]) => key)));
// Keys that are identifiers rather than settings — never shown or compared.
const HIDDEN_KEYS = new Set(['group_id']);

const sameValue = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

/** Rows for display, in section order, with unknown keys appended under "Other". */
export const runConfigRows = (
  config: RunConfig | null | undefined,
  previous: RunConfig | null | undefined,
): RunConfigRow[] => {
  if (!config) return [];
  const current = new Map(Object.entries(config));
  const prior = previous ? new Map(Object.entries(previous)) : null;
  const rows: RunConfigRow[] = [];
  const row = (section: string, key: string, label: string, format: Formatter = plain) => {
    if (!current.has(key) && !prior?.has(key)) return;
    rows.push({
      section,
      key,
      label,
      value: format(current.get(key), config),
      changed: !!prior && !sameValue(current.get(key), prior.get(key)),
    });
  };
  for (const { section, rows: specs } of SECTIONS) {
    for (const [key, label, format] of specs) row(section, key, label, format);
  }
  for (const key of Object.keys(config).sort()) {
    if (!KNOWN_KEYS.has(key) && !HIDDEN_KEYS.has(key)) row('Other', key, key);
  }
  return rows;
};

/** One line that identifies the run's setup: combo · group · summary model · reranker. */
export const runConfigHeadline = (config: RunConfig | null | undefined): string => {
  if (!config) return '';
  const parts: string[] = [];
  if (config.model_combo) parts.push(String(config.model_combo));
  if (config.group_name) parts.push(`group ${String(config.group_name)}`);
  if (config.summary_model) parts.push(`summary ${String(config.summary_model)}`);
  if (config.rerank === true && config.rerank_model) {
    parts.push(`rerank ${String(config.rerank_model)} (${rerankCap(config.max_rerank_candidates)})`);
  } else if (config.rerank === false) {
    parts.push('no rerank');
  }
  return parts.join(' · ');
};
