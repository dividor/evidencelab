import { requestBriefRevise } from '../utils/briefStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

const SUBS = ['Enrolment and attendance', 'Learning outcomes'];

describe('requestBriefRevise sub-sections', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const bodyOf = async (extra: Record<string, unknown>) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
    global.fetch = fetchMock as unknown as typeof fetch;
    await expect(
      requestBriefRevise({ apiBaseUrl: '/api', dataSource: 'wfp', content: 'c', instruction: 'i', ...extra }),
    ).rejects.toThrow();
    return JSON.parse(fetchMock.mock.calls[0][1].body);
  };

  test('an introduction revise sends its sub-headings', async () => {
    expect((await bodyOf({ introducesSubSections: SUBS })).introduces_sub_sections).toEqual(SUBS);
  });

  test('any other revise sends none', async () => {
    expect((await bodyOf({})).introduces_sub_sections).toBeNull();
    expect((await bodyOf({ introducesSubSections: [] })).introduces_sub_sections).toBeNull();
  });
});
