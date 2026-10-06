import type { DocumentSummaryDefaults } from '../../../types/auth';

/**
 * Settings for document summaries generated in the app.
 *
 * They resolve config (the data source's `pipeline.summarize`) → the team's
 * group defaults → the user's choice in the dialog. Only summaries generated
 * here use group defaults; the pipeline uses config alone.
 */
export type SummaryMode = 'map_reduce' | 'single_prompt';

export const SUMMARY_MODES: SummaryMode[] = ['map_reduce', 'single_prompt'];

export const SUMMARY_MODE_LABELS: Record<SummaryMode, string> = {
  map_reduce: 'Map reduce',
  single_prompt: 'Single prompt',
};

export const SUMMARY_MODE_HINTS: Record<SummaryMode, string> = {
  map_reduce: 'Summarises the text in parts, then combines the part summaries.',
  single_prompt: 'Sends all the chosen text to the model in one prompt.',
};

/** The modes with their labels and hints, in display order. */
export const SUMMARY_MODE_OPTIONS = SUMMARY_MODES.map((value) => ({
  value,
  label: value === 'single_prompt' ? SUMMARY_MODE_LABELS.single_prompt : SUMMARY_MODE_LABELS.map_reduce,
  hint: value === 'single_prompt' ? SUMMARY_MODE_HINTS.single_prompt : SUMMARY_MODE_HINTS.map_reduce,
}));

export const SECTION_LABELS: Record<string, string> = {
  front_matter: 'Front matter',
  executive_summary: 'Executive summary',
  acronyms: 'Acronyms',
  introduction: 'Introduction',
  context: 'Context',
  methodology: 'Methodology',
  findings: 'Findings',
  recommendations: 'Recommendations',
  conclusions: 'Conclusions',
  annexes: 'Annexes',
  appendix: 'Appendix',
  bibliography: 'Bibliography',
  other: 'Other',
  untagged: 'No section type',
};

const SECTION_LABEL_MAP = new Map(Object.entries(SECTION_LABELS));

export const sectionLabel = (sectionType: string): string =>
  SECTION_LABEL_MAP.get(sectionType) ?? sectionType;

/** One data source's configured mode and sections. */
export interface DataSourceSummaryDefaults {
  key: string;
  name: string;
  mode: SummaryMode;
  section_types: string[];
}

/** Config defaults from GET /document-summaries/settings. */
export interface SummaryConfigDefaults {
  prompt: string;
  modes: SummaryMode[];
  all_section_types: string[];
  /** Present when the request named a data source. */
  mode?: SummaryMode;
  section_types?: string[];
  single_prompt_context_window?: number | null;
  /** Present when the request named no data source: every source's defaults. */
  data_sources?: DataSourceSummaryDefaults[];
}

export interface SummarySettings {
  mode: SummaryMode;
  sectionTypes: string[];
  prompt: string;
}

export interface SectionSize {
  section_type: string;
  chars: number;
  chunks: number;
}

/** GET /document-summaries/{id}/sections */
export interface DocumentSections {
  has_section_types: boolean;
  sections: SectionSize[];
  /** The single-prompt token limit, and whether the selected model can be
   *  used for a single prompt (it must count its tokens exactly). */
  single_prompt: { context_window: number; available: boolean; reason: string | null };
}

export type SaveMethod = 'ui_map_reduce' | 'ui_single_prompt' | 'ui_edited';

export const methodForMode = (mode: SummaryMode): SaveMethod =>
  mode === 'single_prompt' ? 'ui_single_prompt' : 'ui_map_reduce';

const isMode = (value: unknown): value is SummaryMode =>
  SUMMARY_MODES.includes(value as SummaryMode);

/** Config defaults with the team's group defaults on top. */
export const resolveSummarySettings = (
  config: SummaryConfigDefaults,
  group?: DocumentSummaryDefaults | null,
): SummarySettings => {
  const known = new Set(config.all_section_types);
  const groupSections = group?.docSummarySectionTypes?.filter((s) => known.has(s));
  return {
    mode: isMode(group?.docSummaryMode) ? group!.docSummaryMode as SummaryMode : config.mode ?? 'map_reduce',
    sectionTypes: groupSections?.length ? groupSections : config.section_types ?? config.all_section_types,
    prompt: group?.docSummaryPrompt?.trim() ? group.docSummaryPrompt : config.prompt,
  };
};

/** Characters of text the chosen sections hold (all of it when untagged). */
export const selectedChars = (sections: DocumentSections, chosen: string[]): number => {
  const wanted = new Set(chosen);
  return sections.sections
    .filter((s) => !sections.has_section_types || wanted.has(s.section_type))
    .reduce((total, s) => total + s.chars, 0);
};

export const formatChars = (chars: number): string =>
  chars >= 1000 ? `${Math.round(chars / 1000).toLocaleString()}k` : String(chars);
