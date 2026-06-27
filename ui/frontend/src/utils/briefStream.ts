// Brief tab data layer.
//
// Outline generation hits the thin /brief/outline endpoint; per-section
// "deep research" reuses the existing deep-research assistant
// (streamAssistantChat) and maps its phase/plan/search/sources/token events
// onto the Brief's simpler activity-log + content + sources callbacks.

import { API_KEY } from '../config';
import { SourceReference, SummaryModelConfig } from '../types/api';
import { SearchSettings } from '../types/auth';
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

// Search the corpus for the question and return a de-duplicated sample of the
// most relevant documents, used to ground outline generation in real content.
export const searchCorpusForOutline = async ({
  apiBaseUrl,
  dataSource,
  question,
  signal,
}: {
  apiBaseUrl: string;
  dataSource: string;
  question: string;
  signal?: AbortSignal;
}): Promise<BriefSourceSample[]> => {
  // Grounding only needs representative content, so skip the (slow, CPU-bound)
  // reranker and use fast hybrid retrieval ordered by score.
  const params = new URLSearchParams({
    q: question,
    data_source: dataSource,
    limit: '24',
    rerank: 'false',
  });
  let data: { results?: unknown[] };
  try {
    const res = await fetch(`${apiBaseUrl}/search?${params.toString()}`, {
      method: 'GET',
      headers: buildHeaders(),
      credentials: 'include',
      signal,
    });
    if (!res.ok) return [];
    data = await res.json();
  } catch {
    return []; // grounding is best-effort; outline still generates without it
  }
  const results = Array.isArray(data.results) ? data.results : [];
  const seen = new Set<string>();
  const out: BriefSourceSample[] = [];
  for (const r of results as Record<string, unknown>[]) {
    const title = String(r.document_title || r.title || '').trim();
    if (!title || seen.has(title)) continue;
    seen.add(title);
    out.push({
      title,
      organization: (r.organization as string) || undefined,
      year: (r.year as string) || undefined,
      snippet: typeof r.text === 'string' ? r.text.slice(0, 240) : undefined,
    });
    if (out.length >= 16) break;
  }
  return out;
};

export interface RequestOutlineOptions {
  apiBaseUrl: string;
  dataSource: string;
  question: string;
  model?: string | null;
  sources?: BriefSourceSample[];
  signal?: AbortSignal;
}

export const requestBriefOutline = async ({
  apiBaseUrl,
  dataSource,
  question,
  model,
  sources,
  signal,
}: RequestOutlineOptions): Promise<BriefOutline> => {
  const response = await fetch(`${apiBaseUrl}/brief/outline`, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      question,
      data_source: dataSource,
      model: model ?? null,
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
    title: typeof data.title === 'string' ? data.title : 'Evidence Brief',
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

export interface ResearchSectionOptions {
  apiBaseUrl: string;
  dataSource: string;
  heading: string;
  context?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

// Map the assistant's coarse phases onto an approximate progress percentage so
// the section shows steady movement before tokens start streaming.
const PHASE_PROGRESS: Record<string, number> = {
  planning: 12,
  searching: 30,
  reading: 45,
  synthesizing: 65,
  reflecting: 80,
};

/**
 * Research a single brief section by running one deep-research assistant turn
 * for the heading (plus optional focus context). Citations and sources come
 * straight from the assistant; activity events are derived from its stream.
 */
export const researchBriefSection = async ({
  apiBaseUrl,
  dataSource,
  heading,
  context,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  handlers,
  signal,
}: ResearchSectionOptions): Promise<void> => {
  const focus = (context || '').trim();
  const query = focus
    ? `Write the "${heading}" section of an evidence brief. Focus: ${focus}`
    : `Write the "${heading}" section of an evidence brief.`;

  let latestContent = '';
  let latestSources: SourceReference[] = [];

  await streamAssistantChat({
    apiBaseUrl,
    query,
    dataSource,
    deepResearch: true,
    assistantModelConfig: assistantModelConfig ?? null,
    rerankerModel: rerankerModel ?? null,
    searchSettings: searchSettings ?? null,
    handlers: {
      onPhase: (phase) => {
        const pct = PHASE_PROGRESS[phase];
        if (pct) handlers.onProgress(pct);
        if (phase === 'planning') {
          handlers.onActivity({ tag: 'SCAN', text: 'Planning corpus searches' });
        } else if (phase === 'synthesizing') {
          handlers.onActivity({ tag: 'DRAFT', text: 'Drafting section' });
        }
      },
      onPlan: (queries) => {
        if (queries.length) {
          handlers.onActivity({
            tag: 'SCAN',
            text: `Searching corpus: ${queries.slice(0, 2).join('; ')}`,
          });
        }
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
        handlers.onActivity({ tag: 'DONE', text: 'Section complete' });
        handlers.onDone({ content: latestContent, sources: latestSources });
      },
      onError: (message) => handlers.onError(message),
    },
    signal,
  });
};
