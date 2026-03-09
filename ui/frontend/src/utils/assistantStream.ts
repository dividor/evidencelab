import { SummaryModelConfig, SourceReference } from '../types/api';

interface AssistantDoneData {
  threadId?: string;
  messageId?: string;
  langsmith_trace_url?: string;
}

export interface AssistantStreamHandlers {
  onPhase: (phase: string) => void;
  onPlan: (queries: string[]) => void;
  onSearchStatus: (status: { query: string; resultCount: number }) => void;
  onToken: (fullText: string) => void;
  onSources: (sources: SourceReference[]) => void;
  onDone: (data: AssistantDoneData) => void;
  onError: (message: string) => void;
}

interface AssistantStreamOptions {
  apiBaseUrl: string;
  query: string;
  dataSource?: string;
  threadId?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
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

    case 'search_status':
      handlers.onSearchStatus({
        query: streamedData.query || '',
        resultCount: streamedData.result_count || 0,
      });
      return fullText;

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
        langsmith_trace_url: streamedData.langsmith_trace_url,
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

export const streamAssistantChat = async ({
  apiBaseUrl,
  query,
  dataSource,
  threadId,
  assistantModelConfig,
  handlers,
  signal,
}: AssistantStreamOptions): Promise<void> => {
  const response = await fetch(`${apiBaseUrl}/assistant/chat/stream`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({
      query,
      thread_id: threadId || undefined,
      data_source: dataSource || undefined,
      assistant_model_config: assistantModelConfig || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    handlers.onError(`Request failed: ${response.status} ${response.statusText}`);
    return;
  }

  try {
    const reader = getStreamReader(response);
    await readStream(reader, handlers);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    handlers.onError('Something went wrong with the research assistant.');
  }
};
