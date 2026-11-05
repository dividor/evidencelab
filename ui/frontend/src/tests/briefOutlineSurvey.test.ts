import { act, renderHook } from '@testing-library/react';
import { PROMPT_MAX_CHARS } from '../components/brief/briefTypes';
import { useBrief } from '../components/brief/useBrief';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: false,
}));
jest.mock('../components/brief/briefCitationsApi', () =>
  require('./helpers/fakeBriefCitations').fakeCitationsApi(),
);

const mockStream = jest.fn();
jest.mock('../utils/assistantStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/assistantStream'),
  streamAssistantChat: (...args: unknown[]) => mockStream(...args),
}));
const mockOutline = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/briefStream'),
  requestBriefOutline: (...args: unknown[]) => mockOutline(...args),
}));

const TOPIC = 'School meals';

const generate = async (instructions: string) => {
  const hook = renderHook(() => useBrief({ apiBaseUrl: '/api', dataSource: 'wfp' }));
  act(() => {
    hook.result.current.setQuery(TOPIC);
    hook.result.current.setInstructions(instructions);
  });
  await act(async () => {
    await hook.result.current.generateOutline();
  });
  return mockStream.mock.calls[0][0];
};

describe('the library survey before an outline', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockStream.mockResolvedValue(undefined);
    mockOutline.mockResolvedValue({ title: TOPIC, headings: [{ title: 'Context', level: 1 }] });
  });

  test('instructions at the limit go in their own field, so the question stays short', async () => {
    const instructions = 'x'.repeat(PROMPT_MAX_CHARS);
    const request = await generate(instructions);
    expect(request.query).toBe(TOPIC);
    expect(request.briefSurvey).toEqual({ topic: TOPIC, instructions });
  });

  test('no instructions are sent when there are none', async () => {
    const request = await generate('');
    expect(request.briefSurvey).toEqual({ topic: TOPIC });
  });
});
