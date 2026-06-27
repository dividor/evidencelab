// Brief tab data layer.
//
// Outline generation hits the thin /brief/outline endpoint; per-section "deep
// research" — and the corpus survey that grounds the outline — reuse the
// existing deep-research assistant (streamAssistantChat) and map its
// phase/plan/search/sources/token events onto the Brief's simpler
// activity-log + content + sources callbacks. Briefs never rerank (the local
// cross-encoder runs on CPU and is far too slow for multi-query research).

import { API_KEY } from '../config';
import { SourceReference, SummaryModelConfig } from '../types/api';
import { streamAssistantChat } from './assistantStream';

const getCsrfToken = (): string | null => {
  const match = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
};

const buildHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (API_KEY) headers['X-API-Key'] = API_KEY;
  const csrf = getCsrfToken();
  if (csrf) headers['X-CSRF-Token'] = csrf;
  return headers;
};

export interface BriefOutlineHeading {
  title: string;
  level: number;
}

export interface BriefOutline {
  title: string;
  headings: BriefOutlineHeading[];
}

export interface BriefSourceSample {
  title?: string;
  organization?: string;
  year?: string;
  snippet?: string;
}

export interface RequestOutlineOptions {
  apiBaseUrl: string;
  dataSource: string;
  topic: string;
  instructions?: string | null;
  numHeadings?: number | null;
  model?: string | null;
  sources?: BriefSourceSample[];
  signal?: AbortSignal;
}

export const requestBriefOutline = async ({
  apiBaseUrl,
  dataSource,
  topic,
  instructions,
  numHeadings,
  model,
  sources,
  signal,
}: RequestOutlineOptions): Promise<BriefOutline> => {
  const response = await fetch(`${apiBaseUrl}/brief/outline`, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      question: topic,
      data_source: dataSource,
      model: model ?? null,
      instructions: instructions ?? null,
      num_headings: numHeadings ?? null,
      sources: sources ?? null,
    }),
    signal,
  });
  if (!response.ok) {
    let detail = `Outline request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep generic message */
    }
    throw new Error(detail);
  }
  const data = await response.json();
  return {
    title: typeof data.title === 'string' ? data.title : topic,
    headings: Array.isArray(data.headings)
      ? data.headings.map((h: BriefOutlineHeading) => ({
          title: String(h.title || '').trim(),
          level: h.level === 2 ? 2 : 1,
        }))
      : [],
  };
};

export type BriefActivityTag = 'SCAN' | 'READ' | 'EXTRACT' | 'DRAFT' | 'DONE';

export interface BriefActivityEvent {
  tag: BriefActivityTag;
  text: string;
}

export interface BriefSectionHandlers {
  onActivity: (event: BriefActivityEvent) => void;
  onProgress: (percent: number) => void;
  onToken: (fullText: string) => void;
  onSources: (sources: SourceReference[]) => void;
  onDone: (result: { content: string; sources: SourceReference[] }) => void;
  onError: (message: string) => void;
}

// Map the assistant's coarse phases onto an approximate progress percentage so
// the UI shows steady movement before tokens start streaming.
const PHASE_PROGRESS: Record<string, number> = {
  planning: 12,
  searching: 30,
  reading: 45,
  synthesizing: 65,
  reflecting: 80,
};

export interface RunDeepResearchOptions {
  apiBaseUrl: string;
  dataSource: string;
  query: string;
  doneLabel?: string;
  assistantModelConfig?: SummaryModelConfig | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

/**
 * Run one deep-research assistant turn for an arbitrary query, mapping its
 * stream onto the Brief activity/content/sources callbacks. Reranking is
 * disabled (briefs never rerank).
 */
export const runDeepResearch = async ({
  apiBaseUrl,
  dataSource,
  query,
  doneLabel = 'Section complete',
  assistantModelConfig,
  handlers,
  signal,
}: RunDeepResearchOptions): Promise<void> => {
  let latestContent = '';
  let latestSources: SourceReference[] = [];

  await streamAssistantChat({
    apiBaseUrl,
    query,
    dataSource,
    deepResearch: true,
    assistantModelConfig: assistantModelConfig ?? null,
    rerankerModel: null, // briefs never rerank — the CPU reranker is too slow
    searchSettings: null,
    handlers: {
      onPhase: (phase) => {
        const pct = PHASE_PROGRESS[phase];
        if (pct) handlers.onProgress(pct);
        if (phase === 'planning') {
          handlers.onActivity({ tag: 'SCAN', text: 'Planning corpus searches' });
        } else if (phase === 'synthesizing') {
          handlers.onActivity({ tag: 'DRAFT', text: 'Synthesising findings' });
        }
      },
      onPlan: (queries) => {
        queries.forEach((q) => handlers.onActivity({ tag: 'SCAN', text: `Query: ${q}` }));
      },
      onSearchStatus: (calls) => {
        calls.forEach((call) => {
          handlers.onActivity({
            tag: 'READ',
            text: `Read ${call.resultCount} sources for "${call.query}"`,
          });
        });
      },
      onToken: (fullText) => {
        latestContent = fullText;
        handlers.onProgress(90);
        handlers.onToken(fullText);
      },
      onSources: (sources) => {
        latestSources = sources;
        handlers.onSources(sources);
      },
      onDone: () => {
        handlers.onProgress(100);
        handlers.onActivity({ tag: 'DONE', text: doneLabel });
        handlers.onDone({ content: latestContent, sources: latestSources });
      },
      onError: (message) => handlers.onError(message),
    },
    signal,
  });
};

export interface ResearchSectionOptions {
  apiBaseUrl: string;
  dataSource: string;
  heading: string;
  context?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

/**
 * Research a single brief section by running one deep-research turn for the
 * heading (plus optional focus context). Citations and sources come straight
 * from the assistant; activity events are derived from its stream.
 */
export const researchBriefSection = ({
  apiBaseUrl,
  dataSource,
  heading,
  context,
  assistantModelConfig,
  handlers,
  signal,
}: ResearchSectionOptions): Promise<void> => {
  const focus = (context || '').trim();
  const query = focus
    ? `Write the "${heading}" section of an evidence brief. Focus: ${focus}`
    : `Write the "${heading}" section of an evidence brief.`;
  return runDeepResearch({
    apiBaseUrl,
    dataSource,
    query,
    assistantModelConfig,
    handlers,
    signal,
  });
};
