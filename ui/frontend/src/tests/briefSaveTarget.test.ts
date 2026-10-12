import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import type { RemoteBrief, SavedBrief } from '../components/brief/briefTypes';
import { savedSignature, toSavedBrief, useBrief } from '../components/brief/useBrief';

/**
 * Opening and closing a brief must never create one or write into another.
 * A save waiting in the queue used to decide update-or-create only when it was
 * sent, from whichever brief was open then: after closing, it created a copy;
 * after opening another brief, it wrote into that one. These tests hold the
 * server calls open to put the close (and the next open) inside that window.
 */

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));
jest.mock('axios', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

const mockCreateBrief = jest.fn();
const mockUpdateBrief = jest.fn();
const mockGetBrief = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: (...args: unknown[]) => mockCreateBrief(...args),
  updateBrief: (...args: unknown[]) => mockUpdateBrief(...args),
  getBrief: (...args: unknown[]) => mockGetBrief(...args),
  listMyBriefs: jest.fn(async () => []),
  deleteBriefRemote: jest.fn(),
}));

const DEBOUNCE_MS = 700; // the autosave waits 500 ms after the last change
const A_EDITED = 'Brief A edited';
const A_EDITED_TWICE = 'Brief A edited twice';

const serverBrief = (id: string, title: string): RemoteBrief => ({
  id,
  user_id: 'u-1',
  title,
  query: title,
  data_source: 'wfp',
  voice_profile_id: null,
  content: {
    id,
    title,
    query: title,
    date: 1,
    sectionCount: 1,
    sourceCount: 0,
    sections: [
      { id: `${id}-s1`, title: 'Findings', level: 1, status: 'done', content: `${title} findings.`, sources: [] },
    ],
  },
  owner_name: null,
  can_edit: true,
  shared_with: [],
  created_at: '2026-09-30T10:00:00Z',
  updated_at: '2026-09-30T10:00:00Z',
});
const BRIEFS: Record<string, RemoteBrief> = { A: serverBrief('A', 'Brief A'), B: serverBrief('B', 'Brief B') };

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, DEBOUNCE_MS));
  });

const holdNextUpdate = () => {
  let release!: () => void;
  mockUpdateBrief.mockImplementationOnce(
    (id: string, args: { content: SavedBrief }) =>
      new Promise<RemoteBrief>((resolve) => {
        release = () => resolve(serverBrief(id, args.content.title));
      }),
  );
  return () => release();
};

const updates = () =>
  mockUpdateBrief.mock.calls.map(([id, args]) => [id, (args.content as SavedBrief).title]);
const creates = () => mockCreateBrief.mock.calls.map(([args]) => (args.content as SavedBrief).title);

const renderRemoteBrief = () =>
  renderHook(() => useBrief({ apiBaseUrl: '/api', dataSource: 'wfp', userKey: 'u-1', remote: true }));

const open = async (hook: ReturnType<typeof renderRemoteBrief>, id: string) => {
  await act(async () => {
    hook.result.current.openBriefById(id);
  });
  await waitFor(() => expect(hook.result.current.briefTitle).toBe(BRIEFS[id].title));
};

const retitle = (hook: ReturnType<typeof renderRemoteBrief>, title: string) =>
  act(() => hook.result.current.setBriefTitle(title));

describe('opening and closing a brief', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    mockGetBrief.mockImplementation(async (id: string) => BRIEFS[id]);
    mockUpdateBrief.mockImplementation(async (id: string, args: { content: SavedBrief }) =>
      serverBrief(id, args.content.title),
    );
    mockCreateBrief.mockImplementation(async (args: { content: SavedBrief }) =>
      serverBrief('NEW', args.content.title),
    );
  });

  test('opening a brief and closing it again sends nothing', async () => {
    const hook = renderRemoteBrief();
    await open(hook, 'A');
    await settle();
    act(() => hook.result.current.reset());
    await settle();
    expect(updates()).toEqual([]);
    expect(creates()).toEqual([]);
  });

  test('a change after opening updates that brief', async () => {
    const hook = renderRemoteBrief();
    await open(hook, 'A');
    retitle(hook, A_EDITED);
    await waitFor(() => expect(updates()).toEqual([['A', A_EDITED]]));
    expect(creates()).toEqual([]);
  });

  test('closing while a save is queued sends it to its own brief, never as a new one', async () => {
    const hook = renderRemoteBrief();
    await open(hook, 'A');
    const release = holdNextUpdate();
    retitle(hook, A_EDITED);
    await waitFor(() => expect(mockUpdateBrief).toHaveBeenCalledTimes(1));
    retitle(hook, A_EDITED_TWICE); // queued behind the save in flight
    await settle();

    act(() => hook.result.current.reset());
    await act(async () => release());

    await waitFor(() =>
      expect(updates()).toEqual([
        ['A', A_EDITED],
        ['A', A_EDITED_TWICE],
      ]),
    );
    expect(creates()).toEqual([]);
  });

  test('opening another brief before a queued save goes out leaves the other brief untouched', async () => {
    const hook = renderRemoteBrief();
    await open(hook, 'A');
    const release = holdNextUpdate();
    retitle(hook, A_EDITED);
    await waitFor(() => expect(mockUpdateBrief).toHaveBeenCalledTimes(1));
    retitle(hook, A_EDITED_TWICE);
    await settle();

    act(() => hook.result.current.reset());
    await open(hook, 'B');
    await act(async () => release());
    await settle();

    expect(updates()).toEqual([
      ['A', A_EDITED],
      ['A', A_EDITED_TWICE],
    ]);
    expect(creates()).toEqual([]);
  });

  test("a queued save of one brief is not replaced by another brief's", async () => {
    const hook = renderRemoteBrief();
    await open(hook, 'A');
    const release = holdNextUpdate();
    retitle(hook, A_EDITED);
    await waitFor(() => expect(mockUpdateBrief).toHaveBeenCalledTimes(1));
    retitle(hook, A_EDITED_TWICE);
    await settle();
    act(() => hook.result.current.reset());
    await open(hook, 'B');
    retitle(hook, 'Brief B edited');
    await settle();
    await act(async () => release());

    await waitFor(() =>
      expect(updates()).toEqual([
        ['A', A_EDITED],
        ['A', A_EDITED_TWICE],
        ['B', 'Brief B edited'],
      ]),
    );
  });

  test('a new brief closed before it is first saved is created once, and later saves update it', async () => {
    let releaseCreate!: () => void;
    mockCreateBrief.mockImplementationOnce(
      (args: { content: SavedBrief }) =>
        new Promise<RemoteBrief>((resolve) => {
          releaseCreate = () => resolve(serverBrief('NEW', args.content.title));
        }),
    );
    const hook = renderRemoteBrief();
    act(() => {
      hook.result.current.startFromTemplate('Fresh brief', [{ title: 'Findings', sub: false }]);
    });
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalledTimes(1));
    retitle(hook, 'Fresh brief renamed');
    await settle();

    act(() => hook.result.current.reset());
    await act(async () => releaseCreate());

    await waitFor(() => expect(updates()).toEqual([['NEW', 'Fresh brief renamed']]));
    expect(creates()).toEqual(['Fresh brief']);
  });
});

describe('the saved form of a brief', () => {
  test('its signature ignores only the timestamp', () => {
    const snapshot = {
      id: 'A',
      title: 'Brief A',
      query: 'q',
      sections: [],
      outlineLog: [],
      numberHeadings: false,
      activityId: 'act-1',
      voiceId: null,
      targetWords: null,
      instructions: '',
    };
    const first = toSavedBrief(snapshot);
    const later = { ...toSavedBrief(snapshot), date: first.date + 60_000 };
    expect(savedSignature(later)).toBe(savedSignature(first));
    expect(savedSignature(toSavedBrief({ ...snapshot, title: 'Other' }))).not.toBe(savedSignature(first));
  });
});
