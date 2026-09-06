import { streamAiSummary } from '../utils/aiSummaryStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

describe('streamAiSummary request body', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const captureBody = async (temperature?: number | null) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'nope', text: async () => '' });
    global.fetch = fetchMock as unknown as typeof fetch;
    const handlers = { onPrompt: jest.fn(), onToken: jest.fn(), onDone: jest.fn(), onError: jest.fn() };
    try {
      await streamAiSummary({ apiBaseUrl: '/api', dataSource: 'wfp', query: 'q', results: [], temperature, handlers });
    } catch {
      // the fake response is not a stream; only the request matters here
    }
    expect(fetchMock).toHaveBeenCalled();
    return JSON.parse(fetchMock.mock.calls[0][1].body);
  };

  test('sends the chosen temperature to the summary endpoint', async () => {
    expect((await captureBody(0.7)).temperature).toBe(0.7);
  });

  test('sends 0 as a real value, not as unset', async () => {
    expect((await captureBody(0)).temperature).toBe(0);
  });

  test('omits temperature when none is chosen', async () => {
    expect('temperature' in (await captureBody(null))).toBe(false);
  });
});
