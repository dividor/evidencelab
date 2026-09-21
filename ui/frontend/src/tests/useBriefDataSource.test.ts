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

const mockGetBrief = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: jest.fn(),
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
