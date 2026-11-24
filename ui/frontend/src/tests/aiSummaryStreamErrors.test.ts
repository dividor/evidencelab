import { streamAiSummary } from '../utils/aiSummaryStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

describe('streamAiSummary when the API refuses', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const refuse = async (
    status: number,
    statusText: string,
    body: unknown,
    withOnRefused = false,
  ) => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status,
      statusText,
      json: async () => body,
    }) as unknown as typeof fetch;
    const handlers = {
      onPrompt: jest.fn(),
      onToken: jest.fn(),
      onDone: jest.fn(),
      onError: jest.fn(),
      ...(withOnRefused ? { onRefused: jest.fn() } : {}),
    };
    await streamAiSummary({ apiBaseUrl: '/api', dataSource: 'wfp', query: 'q', results: [], handlers });
    return handlers;
  };

  test('shows the daily AI limit message as the API wrote it', async () => {
    const message =
      "Today's AI allowance for this site has been used. Search still works; AI features return at 00:00 UTC.";
    const handlers = await refuse(429, 'Too Many Requests', { detail: message });
    expect(handlers.onError).toHaveBeenCalledWith(message);
    expect(handlers.onToken).not.toHaveBeenCalled();
  });

  test('hands a refusal to onRefused when the page has one', async () => {
    const message =
      "Today's AI allowance for this site has been used. Search still works; AI features return at 00:00 UTC.";
    const handlers = await refuse(429, 'Too Many Requests', { detail: message }, true);
    expect(handlers.onRefused).toHaveBeenCalledWith(message);
    expect(handlers.onError).not.toHaveBeenCalled();
  });

  test('shows the reason for other refusals', async () => {
    const handlers = await refuse(403, 'Forbidden', { detail: "You don't have access to this data source." });
    expect(handlers.onError).toHaveBeenCalledWith("Request failed: 403: You don't have access to this data source.");
  });
});
