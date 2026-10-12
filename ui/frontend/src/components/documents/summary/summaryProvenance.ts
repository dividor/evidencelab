/**
 * Where a document's summary came from, when, and who made it if a person
 * did: "Edited by a@b.org · 6 Oct 2026, 17:55", "Written by the pipeline ·
 * 12 Jun 2026, 20:24".
 */
export interface SummaryProvenanceDoc {
  summary_user_set?: boolean | null;
  summarization_method?: string | null;
  summary_updated_by?: string | null;
  summary_updated_at?: string | null;
  stages?: { summarize?: { at?: string | null; method?: string | null } | null } | null;
}

export interface SummaryProvenance {
  /** What happened, and who did it when a person did. */
  label: string;
  /** ISO timestamp, when known. */
  at: string | null;
}

const APP_LABELS = new Map([
  ['ui_edited', 'Edited'],
  ['ui_map_reduce', 'Regenerated with AI (map reduce)'],
  ['ui_single_prompt', 'Regenerated with AI (single prompt)'],
]);

const PIPELINE_LABELS = new Map([
  ['llm_on_centroid', 'Written by the pipeline from extracted key sentences'],
  ['centroid_only', 'Extracted by the pipeline (key sentences, no AI summary)'],
]);

export const summaryProvenance = (doc: SummaryProvenanceDoc | null | undefined): SummaryProvenance | null => {
  if (!doc) return null;
  if (doc.summary_user_set) {
    const action = APP_LABELS.get(doc.summarization_method ?? '') ?? 'Changed in the app';
    return {
      label: doc.summary_updated_by ? `${action} by ${doc.summary_updated_by}` : action,
      at: doc.summary_updated_at ?? null,
    };
  }
  const stage = doc.stages?.summarize;
  if (!stage?.at) return null;
  const method = stage.method ?? doc.summarization_method ?? '';
  return { label: PIPELINE_LABELS.get(method) ?? 'Written by the pipeline', at: stage.at };
};

export const formatWhen = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};

export const formatProvenance = (provenance: SummaryProvenance): string =>
  provenance.at ? `${provenance.label} · ${formatWhen(provenance.at)}` : provenance.label;
