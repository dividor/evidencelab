import { act, renderHook, waitFor } from '@testing-library/react';
import type { RemoteBrief } from '../components/brief/briefTypes';
import { useBrief } from '../components/brief/useBrief';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));

jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  requestBriefOutline: jest.fn(),
  researchBriefSection: jest.fn(),
  runDeepResearch: jest.fn(),
}));

// Saving a brief also mirrors it to the activity log over axios.
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: () => Promise.resolve({ data: [] }),
    post: () => Promise.resolve({ data: {} }),
    put: () => Promise.resolve({ data: {} }),
    delete: () => Promise.resolve({ data: {} }),
  },
}));

const mockGetBrief = jest.fn();
const mockCreateBrief = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: (...args: unknown[]) => mockCreateBrief(...args),
  deleteBriefRemote: jest.fn(),
  getBrief: (...args: unknown[]) => mockGetBrief(...args),
  listMyBriefs: jest.fn(async () => []),
  updateBrief: jest.fn(),
}));

const TITLE = 'School feeding';

const remoteBrief = (dataSource: string | null): RemoteBrief => ({
  id: 'b-1',
  user_id: 'u-1',
  title: TITLE,
  query: 'school feeding',
  data_source: dataSource,
  voice_profile_id: null,
  content: {
    id: 'b-1',
    title: TITLE,
    query: 'school feeding',
    date: Date.now(),
    sectionCount: 0,
    sourceCount: 0,
    sections: [],
  },
  owner_name: null,
  can_edit: true,
  shared_with: [],
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
});

const renderBrief = () =>
  renderHook(() =>
    useBrief({ apiBaseUrl: '/api', dataSource: 'uneg', userKey: 'u-1', remote: true }),
  );

describe('useBrief briefDataSource', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  test('is null until a saved brief is opened, then the data source it was saved under', async () => {
    mockGetBrief.mockResolvedValue(remoteBrief('wfp'));
    const { result } = renderBrief();
    expect(result.current.briefDataSource).toBeNull();

    await act(async () => {
      result.current.openBriefById('b-1');
    });
    await waitFor(() => expect(result.current.briefDataSource).toBe('wfp'));
  });

  test('stays null for a saved brief with no recorded data source', async () => {
    mockGetBrief.mockResolvedValue(remoteBrief(null));
    const { result } = renderBrief();
    await act(async () => {
      result.current.openBriefById('b-1');
    });
    await waitFor(() => expect(result.current.briefTitle).toBe(TITLE));
    expect(result.current.briefDataSource).toBeNull();
  });

  test('clears when a new brief is started', async () => {
    mockGetBrief.mockResolvedValue(remoteBrief('wfp'));
    const { result } = renderBrief();
    await act(async () => {
      result.current.openBriefById('b-1');
    });
    await waitFor(() => expect(result.current.briefDataSource).toBe('wfp'));

    act(() => {
      result.current.startManual();
    });
    expect(result.current.briefDataSource).toBeNull();
  });
});

describe('useBrief brief prompt', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockCreateBrief.mockImplementation(async (args: { content: unknown }) => ({
      ...remoteBrief('uneg'),
      content: args.content,
    }));
  });

  test('is restored when a saved brief is opened', async () => {
    const saved = remoteBrief('wfp');
    saved.content = { ...saved.content, instructions: 'Focus on East Africa' };
    mockGetBrief.mockResolvedValue(saved);
    const { result } = renderBrief();
    await act(async () => {
      result.current.openBriefById('b-1');
    });
    await waitFor(() => expect(result.current.instructions).toBe('Focus on East Africa'));
  });

  test('a brief saved without one opens with none, not the previous brief\'s', async () => {
    mockGetBrief.mockResolvedValue(remoteBrief('wfp'));
    const { result } = renderBrief();
    act(() => {
      result.current.setInstructions('Left over from another brief');
    });
    await act(async () => {
      result.current.openBriefById('b-1');
    });
    await waitFor(() => expect(result.current.briefTitle).toBe(TITLE));
    expect(result.current.instructions).toBe('');
  });

  test('is saved with the brief', async () => {
    const { result } = renderBrief();
    act(() => {
      result.current.setInstructions('  Cover 2020 onward  ');
      result.current.startFromTemplate('From a template', [{ title: 'Findings', sub: false }]);
    });
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalled());
    const content = mockCreateBrief.mock.calls[0][0].content;
    expect(content.instructions).toBe('Cover 2020 onward');
  });
});
