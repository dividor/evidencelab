import { SearchResult, SummaryModelConfig } from '../types/api';

interface AiSummaryStreamHandlers {
  onPrompt: (prompt: string) => void;
  onToken: (fullText: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

interface AiSummaryStreamOptions {
  apiBaseUrl: string;
  apiKey?: string;
  dataSource: string;
  query: string;
  results: SearchResult[];
  summaryModelConfig?: SummaryModelConfig | null;
  handlers: AiSummaryStreamHandlers;
}

const buildHeaders = (apiKey?: string): Record<string, string> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
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
    handlers.onDone();
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
  apiKey,
  dataSource,
  query,
  results,
  summaryModelConfig,
  handlers,
}: AiSummaryStreamOptions): Promise<void> => {
  const response = await fetch(`${apiBaseUrl}/ai-summary/stream?data_source=${dataSource}`, {
    method: 'POST',
    headers: buildHeaders(apiKey),
    body: JSON.stringify({
      query,
      results,
      max_results: results.length,
      summary_model: summaryModelConfig?.model || undefined,
      summary_model_config: summaryModelConfig || undefined,
    }),
  });

  try {
    const reader = getStreamReader(response);
    await readStream(reader, handlers);
  } catch (error) {
    handlers.onError('Uh oh. Something went wrong asking the AI.');
  }
};
