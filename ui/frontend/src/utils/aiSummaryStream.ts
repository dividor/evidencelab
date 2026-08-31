import { API_KEY } from '../config';
import { getSessionId } from '../hooks/useActivityLogging';
import { SearchResult, SummaryModelConfig } from '../types/api';

export interface AiSummaryUsage {
  llm_model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

interface AiSummaryDoneData {
  langsmith_trace_url?: string;
  // Informational only: the backend records usage server-side against the
  // search's activity row when the request carried a searchId.
  usage?: AiSummaryUsage;
}

interface AiSummaryStreamHandlers {
  onPrompt: (prompt: string) => void;
  onToken: (fullText: string) => void;
  onDone: (data?: AiSummaryDoneData) => void;
  onError: (message: string) => void;
}

interface AiSummaryStreamOptions {
  apiBaseUrl: string;
  dataSource: string;
  query: string;
  results: SearchResult[];
  summaryModelConfig?: SummaryModelConfig | null;
  // Activity row (search_id) the backend records this summary's token usage
  // onto, server-side (drill-downs reuse the parent search's id and
  // accumulate onto the same row). The anonymous session id is resolved
  // internally.
  searchId?: string | null;
  handlers: AiSummaryStreamHandlers;
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
    console.error('Error parsing SSE data:', error);
    return null;
  }
};

const handleStreamedData = (
  streamedData: any,
  fullText: string,
  handlers: AiSummaryStreamHandlers
): string => {
  if (streamedData.type === 'prompt') {
    handlers.onPrompt(streamedData.prompt);
    return fullText;
  }
  if (streamedData.type === 'token') {
    const nextText = `${fullText}${streamedData.token}`;
    handlers.onToken(nextText);
    return nextText;
  }
  if (streamedData.type === 'done') {
    handlers.onDone({
      langsmith_trace_url: streamedData.langsmith_trace_url,
      usage: streamedData.usage,
    });
    return fullText;
  }
  if (streamedData.type === 'error') {
    handlers.onError(streamedData.error || 'AI summary streaming error.');
    return fullText;
  }
  return fullText;
};

const processStreamMessage = (
  message: string,
  fullText: string,
  handlers: AiSummaryStreamHandlers
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
  handlers: AiSummaryStreamHandlers
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

export const streamAiSummary = async ({
  apiBaseUrl,
  dataSource,
  query,
  results,
  summaryModelConfig,
  searchId,
  handlers,
  signal,
}: AiSummaryStreamOptions): Promise<void> => {
  const response = await fetch(`${apiBaseUrl}/ai-summary/stream?data_source=${dataSource}`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({
      query,
      results,
      max_results: results.length,
      summary_model: summaryModelConfig?.model || undefined,
      summary_model_config: summaryModelConfig || undefined,
      search_id: searchId || undefined,
      session_id: getSessionId(),
    }),
    signal,
  });

  try {
    const reader = getStreamReader(response);
    await readStream(reader, handlers);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    handlers.onError('Uh oh. Something went wrong asking the AI.');
  }
};
