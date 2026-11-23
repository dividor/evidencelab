// Brief tab data layer.
//
// Outline generation hits the thin /brief/outline endpoint; per-section "deep
// research" — and the document-library survey that grounds the outline — reuse
// the existing deep-research assistant (streamAssistantChat) and map its
// phase/plan/search/sources/token events onto the Brief's simpler
// activity-log + content + sources callbacks. Briefs never rerank (the local
// cross-encoder runs on CPU and is far too slow for multi-query research).

import { API_KEY } from '../config';
import { getSessionId } from '../hooks/useActivityLogging';
import { SourceReference, SummaryModelConfig } from '../types/api';
import {
  AssistantSearchSettings,
  BriefOutlineSection,
  BriefSectionPrompt,
  BriefSurveyPrompt,
  streamAssistantChat,
} from './assistantStream';

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
  // The brief's stable activity id, so the backend records outline LLM
  // usage server-side onto the brief's activity row (the anonymous session
  // id is resolved internally).
  activityId?: string | null;
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
  activityId,
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
      activity_id: activityId ?? null,
      session_id: getSessionId(),
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

/**
 * Surgically revise one section's markdown per an instruction (Brief "Edit").
 * A single backend LLM copy-edit — NOT deep research — so the section keeps its
 * wording + inline [n] citations. Returns the revised markdown.
 */
export const requestBriefRevise = async ({
  apiBaseUrl,
  dataSource,
  content,
  instruction,
  model,
  voiceInstructions,
  introducesSubSections = null,
  activityId,
  signal,
}: {
  apiBaseUrl: string;
  dataSource: string;
  content: string;
  instruction: string;
  model?: string | null;
  voiceInstructions?: string | null;
  // Sub-headings the section introduces; keeps a revision an introduction.
  introducesSubSections?: string[] | null;
  // Usage-recording context (see RequestOutlineOptions).
  activityId?: string | null;
  signal?: AbortSignal;
}): Promise<string> => {
  const response = await fetch(`${apiBaseUrl}/brief/revise`, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      content,
      instruction,
      data_source: dataSource,
      model: model ?? null,
      voice_instructions: voiceInstructions ?? null,
      introduces_sub_sections: introducesSubSections?.length ? introducesSubSections : null,
      activity_id: activityId ?? null,
      session_id: getSessionId(),
    }),
    signal,
  });
  if (!response.ok) {
    let detail = `Edit request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep generic message */
    }
    throw new Error(detail);
  }
  const data = await response.json();
  return typeof data.content === 'string' ? data.content : content;
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
  // The finished section as the agent returned it: its text with the agent's
  // own `[n]` markers, its sources as streamed, and the agent run id. The
  // browser records it with the API as the section's original; the API
  // numbers it across the brief.
  onDone: (result: { content: string; sources: SourceReference[]; runId?: string }) => void;
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
  // Reranker + search settings. Logged-in briefs pass the group's settings so
  // they search like the rest of the app; otherwise these are null (no rerank —
  // the default CPU cross-encoder is too slow for multi-query research).
  rerankerModel?: string | null;
  searchSettings?: AssistantSearchSettings | null;
  publishedAfter?: string | null;
  // The brief's stable activity id, so the backend records this research
  // turn's token usage onto the brief's activity row (typed 'brief' via
  // the stream's usageContext).
  activityId?: string | null;
  // Target length of the written text in words (see briefLength.ts).
  targetWords?: number | null;
  // Sub-headings this text introduces (see briefIntro.ts); null otherwise.
  introducesSubSections?: string[] | null;
  // A brief section's prompt parts; the API writes the prompt from them.
  briefSection?: BriefSectionPrompt | null;
  // The survey before an outline; the API writes the prompt from these parts.
  briefSurvey?: BriefSurveyPrompt | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

/**
 * Run one deep-research assistant turn for an arbitrary query, mapping its
 * stream onto the Brief activity/content/sources callbacks.
 */
export const runDeepResearch = async ({
  apiBaseUrl,
  dataSource,
  query,
  doneLabel = 'Section complete',
  assistantModelConfig,
  rerankerModel = null,
  searchSettings = null,
  publishedAfter = null,
  activityId = null,
  targetWords = null,
  introducesSubSections = null,
  briefSection = null,
  briefSurvey = null,
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
    rerankerModel: rerankerModel ?? null,
    searchSettings: searchSettings ?? null,
    publishedAfter: publishedAfter ?? null,
    activityId: activityId ?? null,
    usageContext: 'brief',
    targetWords: targetWords ?? null,
    introducesSubSections,
    briefSection,
    briefSurvey,
    handlers: {
      onPhase: (phase) => {
        const pct = PHASE_PROGRESS[phase];
        if (pct) handlers.onProgress(pct);
        if (phase === 'planning') {
          handlers.onActivity({ tag: 'SCAN', text: 'Planning document-library searches' });
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
      onDone: (data) => {
        handlers.onProgress(100);
        handlers.onActivity({ tag: 'DONE', text: doneLabel });
        handlers.onDone({ content: latestContent, sources: latestSources, runId: data.runId });
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
  // The whole brief, in order, with each written section's text, and the
  // index of the section being written: the API writes the section's place
  // in the brief (its parent, what other sections cover) into the prompt.
  outline: BriefOutlineSection[];
  currentIndex: number;
  context?: string | null;
  // Overall brief subject — situates the section and steers its searches.
  briefTopic?: string | null;
  // Author guidance that shaped the outline; also steers section research.
  briefInstructions?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: AssistantSearchSettings | null;
  // Update: the current draft, the user's instruction, and the ISO date after
  // which the library search is constrained.
  mode?: SectionResearchMode;
  existingContent?: string | null;
  instruction?: string | null;
  publishedAfterIso?: string | null;
  // Voice & tone profile instructions applied to the section's writing.
  voiceInstructions?: string | null;
  // Usage-recording context (see RunDeepResearchOptions).
  activityId?: string | null;
  // Target length of the section in words (see briefLength.ts).
  targetWords?: number | null;
  // Sub-headings this section introduces, for a top-level heading that has
  // them (see briefIntro.ts); null otherwise.
  introducesSubSections?: string[] | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

// 'generate' writes the section; 'update' folds in sources published since
// `publishedAfterIso` and keeps the current draft. (Edit uses /brief/revise.)
export type SectionResearchMode = 'generate' | 'update';

/**
 * Heuristic for a deep-research run that returned process narration instead of
 * the section ("I'll go research that…"): it read sources but produced short
 * text with no [n] citation markers. Such a result is treated as a failed run
 * (fail loud, keep the section pending) rather than stored as content.
 */
export const isLikelyNonAnswer = (
  content: string,
  sourceCount: number,
  targetWords?: number | null,
): boolean => {
  const text = (content || '').trim();
  if (!text) return true;
  const hasCitations = /\[\d+(?:,\s*\d+)*\]/.test(text);
  // A short section is only suspicious relative to the length asked for: with
  // a target of 100 words, 700 characters is a complete answer, not narration.
  const shortLimit = targetWords ? Math.min(800, targetWords * 3) : 800;
  return sourceCount >= 3 && !hasCitations && text.length < shortLimit;
};

/**
 * The parts of one section's research prompt, as the API takes them; empty
 * parts are left out.
 */
export const sectionPromptParts = ({
  outline,
  currentIndex,
  briefTopic,
  briefInstructions,
  context,
  mode = 'generate',
  existingContent,
  instruction,
  publishedAfterIso,
  voiceInstructions,
}: {
  outline: BriefOutlineSection[];
  currentIndex: number;
  briefTopic?: string | null;
  briefInstructions?: string | null;
  context?: string | null;
  mode?: SectionResearchMode;
  existingContent?: string | null;
  instruction?: string | null;
  publishedAfterIso?: string | null;
  voiceInstructions?: string | null;
}): BriefSectionPrompt => ({
  outline,
  current: currentIndex,
  mode,
  topic: briefTopic || undefined,
  instructions: briefInstructions || undefined,
  focus: context || undefined,
  draft: mode === 'update' ? existingContent || undefined : undefined,
  instruction: instruction || undefined,
  published_after: publishedAfterIso || undefined,
  voice_instructions: voiceInstructions || undefined,
});

/**
 * Research a single brief section by running one deep-research turn for the
 * heading (plus its place in the brief and any focus context). Citations and
 * sources come straight from the assistant; activity events derive from its
 * stream.
 */
export const researchBriefSection = ({
  apiBaseUrl,
  dataSource,
  heading,
  outline,
  currentIndex,
  context,
  briefTopic,
  briefInstructions,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  mode = 'generate',
  existingContent,
  instruction,
  publishedAfterIso,
  voiceInstructions,
  activityId,
  targetWords,
  introducesSubSections = null,
  handlers,
  signal,
}: ResearchSectionOptions): Promise<void> =>
  runDeepResearch({
    apiBaseUrl,
    dataSource,
    query: heading,
    briefSection: sectionPromptParts({
      outline,
      currentIndex,
      briefTopic,
      briefInstructions,
      context,
      mode,
      existingContent,
      instruction,
      publishedAfterIso,
      voiceInstructions,
    }),
    assistantModelConfig,
    rerankerModel,
    searchSettings,
    // Update also constrains the *search* to newer documents via a publish-date
    // filter the backend applies to the Qdrant query (belt-and-braces with the
    // prompt instruction).
    publishedAfter: mode === 'update' ? publishedAfterIso : null,
    activityId,
    targetWords,
    introducesSubSections,
    handlers,
    signal,
  });
