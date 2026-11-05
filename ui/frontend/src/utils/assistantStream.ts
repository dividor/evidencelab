import { API_KEY } from '../config';
import { getSessionId } from '../hooks/useActivityLogging';
import { SummaryModelConfig, SourceReference, SearchToolCall } from '../types/api';
import { SearchSettings } from '../types/auth';

export interface AssistantUsage {
  llm_model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export interface AssistantDoneData {
  threadId?: string;
  messageId?: string;
  // The agent run behind this turn (the Brief stores it with a section's
  // original output, for tracing).
  runId?: string;
  // Link to the LLM trace behind this turn, when the deployment traces calls.
  trace_url?: string;
  // Informational only: the backend records usage server-side against the
  // activity row when the request carried an activityId.
  usage?: AssistantUsage;
}

export interface AssistantStreamHandlers {
  onPhase: (phase: string) => void;
  onPlan: (queries: string[]) => void;
  onSearchStatus: (toolCalls: SearchToolCall[]) => void;
  onToken: (fullText: string) => void;
  onSources: (sources: SourceReference[]) => void;
  onDone: (data: AssistantDoneData) => void;
  onError: (message: string) => void;
}

interface ConversationMessage {
  role: string;
  content: string;
  // Assistant messages also carry their previously emitted sources so the
  // backend can re-use the same citation numbers in follow-up turns.
  sources?: SourceReference[];
}

/**
 * Search settings for an assistant turn: the user's search settings plus the
 * selected model combo's reranker cap and embedding model, so the assistant
 * searches like the search tab.
 */
export type AssistantSearchSettings = Partial<SearchSettings> & {
  rerankModelPageSize?: number | null;
  embeddingModel?: string | null;
};

/** One section of a brief as its research prompt describes the outline: its
 *  text only when it is written. */
export interface BriefOutlineSection {
  title: string;
  level: number;
  content?: string;
}

/**
 * The parts of a Brief section's research prompt. The API writes the prompt
 * from them (ui/backend/services/brief_section_prompt.py); `current` is the
 * index in `outline` of the section being written.
 */
export interface BriefSectionPrompt {
  outline: BriefOutlineSection[];
  current: number;
  mode: 'generate' | 'update';
  topic?: string;
  instructions?: string;
  focus?: string;
  draft?: string;
  instruction?: string;
  published_after?: string;
  voice_instructions?: string;
}

// The survey run before a brief's outline; the API writes its prompt.
export interface BriefSurveyPrompt {
  topic: string;
  instructions?: string;
}

interface AssistantStreamOptions {
  apiBaseUrl: string;
  query: string;
  dataSource?: string;
  threadId?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: AssistantSearchSettings | null;
  deepResearch?: boolean;
  conversationHistory?: ConversationMessage[];
  // ISO date; constrains the library search to documents published on/after it
  // (Brief "Update" action). Sent inside search_settings.published_after.
  publishedAfter?: string | null;
  // Activity row (search_id) the backend records this turn's token usage
  // onto, server-side. Brief sections pass their brief's stable id so all
  // section research accumulates onto one row, with usageContext 'brief' so
  // a newly created row is typed 'brief'. The anonymous session id is
  // resolved internally.
  activityId?: string | null;
  usageContext?: 'brief' | null;
  // Target length of the written answer in words (deep research). The backend
  // asks the coordinator for that length and raises its token ceiling to fit.
  targetWords?: number | null;
  // Brief: the sub-headings of the section being written when it is a
  // top-level heading's introduction (no headings, none of their detail).
  introducesSubSections?: string[] | null;
  // Brief: the section being researched; the API writes its prompt, and
  // `query` is then the section heading.
  briefSection?: BriefSectionPrompt | null;
  briefSurvey?: BriefSurveyPrompt | null;
  handlers: AssistantStreamHandlers;
  signal?: AbortSignal;
}

const getCsrfToken = (): string | null => {
  const match = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
};

const buildHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY;
  }
  const csrfToken = getCsrfToken();
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  return headers;
};

const getStreamReader = (response: Response): ReadableStreamDefaultReader<Uint8Array> => {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Failed to get stream reader');
  }
  return reader;
};

const splitBuffer = (buffer: string): { messages: string[]; remaining: string } => {
  const messages = buffer.split('\n\n');
  const remaining = messages.pop() || '';
  return { messages, remaining };
};

const parseStreamedPayload = (payload: string): any | null => {
  try {
    return JSON.parse(payload);
  } catch (error) {
    console.error('Error parsing assistant SSE data:', error);
    return null;
  }
};

const handleStreamedData = (
  streamedData: any,
  fullText: string,
  handlers: AssistantStreamHandlers
): string => {
  switch (streamedData.type) {
    case 'phase':
      handlers.onPhase(streamedData.phase);
      return fullText;

    case 'plan':
      handlers.onPlan(streamedData.queries || []);
      return fullText;

    case 'search_status': {
      const queries: SearchToolCall[] = (streamedData.queries || []).map(
        (q: any) => ({
          query: q.query || '',
          resultCount: q.result_count || 0,
          results: (q.results || []).map((r: any) => ({
            title: r.title || 'Untitled',
            text: r.text || '',
          })),
        })
      );
      handlers.onSearchStatus(queries);
      return fullText;
    }

    case 'token': {
      // The assistant sends the full synthesis as one token event
      const nextText = streamedData.token || '';
      handlers.onToken(nextText);
      return nextText;
    }

    case 'sources':
      handlers.onSources(streamedData.sources || []);
      return fullText;

    case 'done':
      handlers.onDone({
        threadId: streamedData.threadId,
        messageId: streamedData.messageId,
        runId: streamedData.runId,
        trace_url: streamedData.trace_url,
        usage: streamedData.usage,
      });
      return fullText;

    case 'error':
      handlers.onError(streamedData.error || 'Research assistant error.');
      return fullText;

    default:
      return fullText;
  }
};

const processStreamMessage = (
  message: string,
  fullText: string,
  handlers: AssistantStreamHandlers
): string => {
  if (!message.trim().startsWith('data: ')) {
    return fullText;
  }
  const payload = message.trim().slice(6);
  const streamedData = parseStreamedPayload(payload);
  if (!streamedData) {
    return fullText;
  }
  return handleStreamedData(streamedData, fullText, handlers);
};

const readStream = async (
  reader: ReadableStreamDefaultReader<Uint8Array>,
  handlers: AssistantStreamHandlers
): Promise<void> => {
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    buffer += chunk;

    const { messages, remaining } = splitBuffer(buffer);
    buffer = remaining;

    messages.forEach((message) => {
      fullText = processStreamMessage(message, fullText, handlers);
    });
  }
};

/** Convert frontend SearchSettings to backend search_settings format. */
const buildSearchSettingsPayload = (
  settings?: AssistantSearchSettings | null,
): Record<string, unknown> | undefined => {
  if (!settings) return undefined;
  const payload: Record<string, unknown> = {};
  if (settings.denseWeight != null) payload.dense_weight = settings.denseWeight;
  if (settings.recencyBoost != null) payload.recency_boost = settings.recencyBoost;
  if (settings.recencyWeight != null) payload.recency_weight = settings.recencyWeight;
  if (settings.recencyScaleDays != null) payload.recency_scale_days = settings.recencyScaleDays;
  if (settings.sectionTypes != null) payload.section_types = settings.sectionTypes;
  if (settings.keywordBoostShortQueries != null) payload.keyword_boost_short_queries = settings.keywordBoostShortQueries;
  if (settings.minChunkSize != null) payload.min_chunk_size = settings.minChunkSize;
  if (settings.fieldBoost != null) payload.field_boost_enabled = settings.fieldBoost;
  if (settings.wideSearch != null) payload.wide_search = settings.wideSearch;
  if (settings.wideGroupSize != null) payload.wide_group_size = settings.wideGroupSize;
  if (settings.wideLimit != null) payload.wide_limit = settings.wideLimit;
  if (settings.rerankModelPageSize != null) payload.rerank_model_page_size = settings.rerankModelPageSize;
  if (settings.embeddingModel != null) payload.embedding_model = settings.embeddingModel;
  if (settings.fieldBoostFields != null && Object.keys(settings.fieldBoostFields).length > 0) {
    payload.field_boost_fields = settings.fieldBoostFields;
  }
  return Object.keys(payload).length > 0 ? payload : undefined;
};

/**
 * What a refused request says, using the API's own reason so the person sees
 * why: its message, or for a 422 each rejected field and what is wrong with it.
 */
export const requestFailureMessage = async (response: Response): Promise<string> => {
  const prefix = `Request failed: ${response.status}`;
  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    return `${prefix} ${response.statusText}`;
  }
  if (typeof detail === 'string') return `${prefix}: ${detail}`;
  if (Array.isArray(detail)) {
    const fields = detail.map((e: { loc?: unknown[]; msg?: string }) => {
      const field = (e.loc ?? []).filter((part) => part !== 'body').join('.');
      return `${field}: ${e.msg}`;
    });
    return `${prefix}: ${fields.join('; ')}`;
  }
  return `${prefix} ${response.statusText}`;
};

/** The JSON body of a chat request. */
const buildRequestBody = ({
  query,
  dataSource,
  threadId,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  deepResearch,
  conversationHistory,
  publishedAfter,
  activityId,
  usageContext,
  targetWords,
  introducesSubSections,
  briefSection,
  briefSurvey,
}: AssistantStreamOptions): string => {
  // Fold the per-request publish-date cutoff into the search_settings payload
  // (backend allows extra keys and applies it as a Qdrant range filter).
  const settingsPayload = buildSearchSettingsPayload(searchSettings);
  const searchSettingsBody = publishedAfter
    ? { ...(settingsPayload || {}), published_after: publishedAfter }
    : settingsPayload;
  return JSON.stringify({
    query,
    thread_id: threadId || undefined,
    data_source: dataSource || undefined,
    assistant_model_config: assistantModelConfig || undefined,
    reranker_model: rerankerModel || undefined,
    search_settings: searchSettingsBody,
    deep_research: deepResearch || undefined,
    conversation_history: conversationHistory?.length ? conversationHistory : undefined,
    activity_id: activityId || undefined,
    session_id: getSessionId(),
    usage_context: usageContext || undefined,
    target_words: targetWords || undefined,
    introduces_sub_sections: introducesSubSections?.length ? introducesSubSections : undefined,
    brief_section: briefSection || undefined,
    brief_survey: briefSurvey || undefined,
  });
};

export const streamAssistantChat = async (options: AssistantStreamOptions): Promise<void> => {
  const { apiBaseUrl, handlers, signal } = options;
  const response = await fetch(`${apiBaseUrl}/assistant/chat/stream`, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'include',
    body: buildRequestBody(options),
    signal,
  });

  if (!response.ok) {
    handlers.onError(await requestFailureMessage(response));
    return;
  }

  try {
    const reader = getStreamReader(response);
    await readStream(reader, handlers);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    const msg = error instanceof Error ? error.message : 'Unknown error';
    console.error('Assistant stream error:', error);
    handlers.onError(`Research assistant connection error: ${msg}`);
  }
};
