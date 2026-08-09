// Brief tab data layer.
//
// Outline generation hits the thin /brief/outline endpoint; per-section "deep
// research" — and the document-library survey that grounds the outline — reuse
// the existing deep-research assistant (streamAssistantChat) and map its
// phase/plan/search/sources/token events onto the Brief's simpler
// activity-log + content + sources callbacks. Briefs never rerank (the local
// cross-encoder runs on CPU and is far too slow for multi-query research).

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
  signal,
}: {
  apiBaseUrl: string;
  dataSource: string;
  content: string;
  instruction: string;
  model?: string | null;
  voiceInstructions?: string | null;
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
  // Reranker + search settings. Logged-in briefs pass the group's settings so
  // they search like the rest of the app; otherwise these are null (no rerank —
  // the default CPU cross-encoder is too slow for multi-query research).
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
  publishedAfter?: string | null;
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
  // Overall brief subject — situates the section and steers its searches.
  briefTopic?: string | null;
  // Author guidance that shaped the outline; also steers section research.
  briefInstructions?: string | null;
  // For sub-sections (level 2): the parent section title, so the section stays
  // scoped to its parent and the generated queries reflect that context.
  parentTitle?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
  // Edit/Update: the mode, the current draft, the user's instruction, and (for
  // Update) the ISO date after which the library search is constrained.
  mode?: SectionResearchMode;
  existingContent?: string | null;
  instruction?: string | null;
  publishedAfterIso?: string | null;
  // Voice & tone profile instructions applied to the section's writing.
  voiceInstructions?: string | null;
  handlers: BriefSectionHandlers;
  signal?: AbortSignal;
}

// 'edit' revises the existing draft per an instruction; 'update' folds in
// sources published since `publishedAfterIso`. Both keep the current draft.
export type SectionResearchMode = 'generate' | 'edit' | 'update';

const updateInstruction = (instr: string, publishedAfterIso?: string | null): string => {
  const after = (publishedAfterIso || '').slice(0, 10);
  const base = after
    ? `Search the document library for relevant sources PUBLISHED AFTER ${after} and fold any new findings into the draft, citing them. Keep the existing content; add or refresh only where newer evidence warrants. If no newer sources are found, return the draft unchanged and note that no newer sources were available.`
    : 'Search the document library for the most recent relevant sources and fold any new findings into the draft, citing them.';
  return instr ? `${base} Additional instruction: ${instr}` : base;
};

// Update: preserve the existing draft; the model folds in newer sources rather
// than rewriting, returning the FULL section with a coherent sequential [n]
// citation set. (Edit uses the backend /brief/revise .j2 prompt, not this.)
const buildReviseQuery = (args: {
  scope: string;
  draft: string;
  instr: string;
  guidance: string;
  publishedAfterIso?: string | null;
}): string => {
  const parts = [
    `You are revising ${args.scope}.`,
    `Here is the current draft of the section. Preserve its wording, structure and citations except where the instruction below requires a change:\n\n"""\n${args.draft}\n"""`,
    updateInstruction(args.instr, args.publishedAfterIso),
    'Return the FULL revised section as markdown with sequential [n] citation markers and cite a source for every claim.',
  ];
  if (args.guidance) parts.push(`Overall brief guidance: ${args.guidance}`);
  return parts.join(' ');
};

const buildGenerateQuery = (args: {
  scope: string;
  parent: string;
  guidance: string;
  focus: string;
}): string => {
  const parts = [`Write ${args.scope}.`];
  if (args.parent) {
    parts.push(
      `This section sits under the parent section "${args.parent}" — keep it specifically about that aspect of the brief and avoid repeating material that belongs in sibling sections.`,
    );
  }
  parts.push(
    'Search the document library for evidence relevant to this specific section and cite a source for every claim.',
  );
  if (args.guidance) parts.push(`Overall brief guidance: ${args.guidance}`);
  if (args.focus) parts.push(`Focus for this section: ${args.focus}`);
  return parts.join(' ');
};

/**
 * Build the deep-research instruction for one brief section. For generate it
 * weaves in the brief topic, parent section and author guidance; for edit/update
 * it embeds the current draft with revise-don't-replace semantics.
 */
export const buildSectionQuery = ({
  heading,
  briefTopic,
  briefInstructions,
  parentTitle,
  context,
  mode = 'generate',
  existingContent,
  instruction,
  publishedAfterIso,
  voiceInstructions,
}: {
  heading: string;
  briefTopic?: string | null;
  briefInstructions?: string | null;
  parentTitle?: string | null;
  context?: string | null;
  mode?: SectionResearchMode;
  existingContent?: string | null;
  instruction?: string | null;
  publishedAfterIso?: string | null;
  voiceInstructions?: string | null;
}): string => {
  const topic = (briefTopic || '').trim();
  const guidance = (briefInstructions || '').trim();
  const draft = (existingContent || '').trim();
  const voice = (voiceInstructions || '').trim();
  const scope = topic
    ? `the "${heading}" section of an evidence brief on "${topic}"`
    : `the "${heading}" section of an evidence brief`;

  const base =
    mode === 'update' && draft
      ? buildReviseQuery({
          scope,
          draft,
          instr: (instruction || '').trim(),
          guidance,
          publishedAfterIso,
        })
      : buildGenerateQuery({
          scope,
          parent: (parentTitle || '').trim(),
          guidance,
          focus: (context || '').trim(),
        });
  return voice ? `${base} Voice & tone profile — write the section in this style: ${voice}` : base;
};

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
  context,
  briefTopic,
  briefInstructions,
  parentTitle,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  mode = 'generate',
  existingContent,
  instruction,
  publishedAfterIso,
  voiceInstructions,
  handlers,
  signal,
}: ResearchSectionOptions): Promise<void> => {
  const query = buildSectionQuery({
    heading,
    briefTopic,
    briefInstructions,
    parentTitle,
    context,
    mode,
    existingContent,
    instruction,
    publishedAfterIso,
    voiceInstructions,
  });
  return runDeepResearch({
    apiBaseUrl,
    dataSource,
    query,
    assistantModelConfig,
    rerankerModel,
    searchSettings,
    // Update also constrains the *search* to newer documents via a publish-date
    // filter the backend applies to the Qdrant query (belt-and-braces with the
    // prompt instruction above).
    publishedAfter: mode === 'update' ? publishedAfterIso : null,
    handlers,
    signal,
  });
};
