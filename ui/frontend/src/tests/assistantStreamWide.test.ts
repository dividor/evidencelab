import { streamAssistantChat } from '../utils/assistantStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

describe('streamAssistantChat search_settings payload', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const captureBody = async (searchSettings: Record<string, unknown>) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'nope', text: async () => '' });
    global.fetch = fetchMock as unknown as typeof fetch;
    const handlers = {
      onPhase: jest.fn(), onPlan: jest.fn(), onSearchStatus: jest.fn(), onToken: jest.fn(),
      onSources: jest.fn(), onDone: jest.fn(), onError: jest.fn(),
    };
    try {
      await streamAssistantChat({ apiBaseUrl: '/api', query: 'q', dataSource: 'wfp', searchSettings, handlers } as any);
    } catch {
      // the fake response is not a stream; only the request matters here
    }
    expect(fetchMock).toHaveBeenCalled();
    return JSON.parse(fetchMock.mock.calls[0][1].body);
  };

  test('forwards wide search settings to the assistant and brief searches', async () => {
    const body = await captureBody({ denseWeight: 0.9, wideSearch: true, wideGroupSize: 3, wideLimit: 10 });
    expect(body.search_settings).toMatchObject({ dense_weight: 0.9, wide_search: true, wide_group_size: 3, wide_limit: 10 });
  });

  test('omits wide keys when not set', async () => {
    const body = await captureBody({ denseWeight: 0.9 });
    expect(body.search_settings).toEqual({ dense_weight: 0.9 });
  });
});
