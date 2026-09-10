import { streamAssistantChat } from '../utils/assistantStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

describe('streamAssistantChat target_words', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const captureBody = async (extra: Record<string, unknown>) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'nope', text: async () => '' });
    global.fetch = fetchMock as unknown as typeof fetch;
    const handlers = {
      onPhase: jest.fn(), onPlan: jest.fn(), onSearchStatus: jest.fn(), onToken: jest.fn(),
      onSources: jest.fn(), onDone: jest.fn(), onError: jest.fn(),
    };
    try {
      await streamAssistantChat({ apiBaseUrl: '/api', query: 'q', dataSource: 'wfp', deepResearch: true, handlers, ...extra } as any);
    } catch {
      // the fake response is not a stream; only the request matters here
    }
    return JSON.parse(fetchMock.mock.calls[0][1].body);
  };

  test('sends the length target to the backend', async () => {
    const body = await captureBody({ targetWords: 350 });
    expect(body.target_words).toBe(350);
  });

  test('omits the field when there is no target', async () => {
    expect(await captureBody({})).not.toHaveProperty('target_words');
    expect(await captureBody({ targetWords: null })).not.toHaveProperty('target_words');
  });
});
