import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import type { RemoteBrief, SavedBrief } from '../components/brief/briefTypes';
import { useBrief } from '../components/brief/useBrief';

/**
 * A signed-in brief is saved to the server through a queue that sends one
 * save at a time. These tests hold the server calls open to put a section's
 * research completion inside each window of that queue, and check that the
 * finished section always reaches the server.
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

const mockResearchSection = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/briefStream'),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
}));

const mockCreateBrief = jest.fn();
const mockUpdateBrief = jest.fn();
const mockListMyBriefs = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: (...args: unknown[]) => mockCreateBrief(...args),
  updateBrief: (...args: unknown[]) => mockUpdateBrief(...args),
  listMyBriefs: (...args: unknown[]) => mockListMyBriefs(...args),
  getBrief: jest.fn(),
  deleteBriefRemote: jest.fn(),
}));

const SECTION_TEXT = 'School feeding raised enrolment in the districts it covered [1].';
const source = { chunkId: 'c1', docId: 'd1', title: 'Doc', text: 'x', score: 0.5, page: 1, index: 1 };

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}
const deferred = <T>(): Deferred<T> => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

const serverBrief = (content: SavedBrief): RemoteBrief => ({
  id: 'srv-1',
  user_id: 'u-1',
  title: content.title,
  query: content.query,
  data_source: 'wfp',
  voice_profile_id: null,
  content,
  owner_name: null,
  can_edit: true,
  shared_with: [],
  created_at: '2026-09-30T10:00:00Z',
  updated_at: '2026-09-30T10:00:00Z',
});

// The content the server last received for the first section, from any save.
const lastSavedSectionText = (): string | undefined => {
  const saves = [
    ...mockCreateBrief.mock.calls.map(([args]) => args.content as SavedBrief),
    ...mockUpdateBrief.mock.calls.map(([, args]) => args.content as SavedBrief),
  ];
  return saves.length ? saves[saves.length - 1].sections[0]?.content : undefined;
};

const renderRemoteBrief = () =>
  renderHook(() => useBrief({ apiBaseUrl: '/api', dataSource: 'wfp', userKey: 'u-1', remote: true }));

const startBrief = (hook: ReturnType<typeof renderRemoteBrief>) =>
  act(() => {
    hook.result.current.startFromTemplate('School feeding', [{ title: 'Education outcomes', sub: false }]);
  });

const researchFirstSection = async (hook: ReturnType<typeof renderRemoteBrief>) => {
  const id = hook.result.current.sections[0].id;
  await act(async () => {
    await hook.result.current.regenerate(id, null);
  });
};

describe('saving a researched section to the server', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    mockListMyBriefs.mockResolvedValue([]);
    mockUpdateBrief.mockImplementation(async (_id: string, args: { content: SavedBrief }) =>
      serverBrief(args.content),
    );
    mockResearchSection.mockImplementation(async ({ handlers }: any) => {
      handlers.onSources([source]);
      handlers.onDone({ content: SECTION_TEXT, sources: [source] });
    });
  });

  test('a section finished while the brief is first being created is saved once it exists', async () => {
    const create = deferred<RemoteBrief>();
    mockCreateBrief.mockReturnValue(create.promise);
    const hook = renderRemoteBrief();
    startBrief(hook);
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalledTimes(1));

    await researchFirstSection(hook);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 700)); // the autosave's debounce
      create.resolve(serverBrief(mockCreateBrief.mock.calls[0][0].content));
    });

    await waitFor(() => expect(lastSavedSectionText()).toBe(SECTION_TEXT));
  });

  test('a section finished while the saved-brief list refreshes is still saved', async () => {
    mockCreateBrief.mockImplementation(async (args: { content: SavedBrief }) => serverBrief(args.content));
    const refresh = deferred<never[]>();
    const hook = renderRemoteBrief();
    await waitFor(() => expect(mockListMyBriefs).toHaveBeenCalled()); // the initial history load
    mockListMyBriefs.mockReturnValue(refresh.promise);

    startBrief(hook);
    // The brief is created, then the queue refreshes the list and waits on it.
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockListMyBriefs.mock.results.some((r) => r.value === refresh.promise)).toBe(true));

    await researchFirstSection(hook);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 700)); // the autosave's debounce
      refresh.resolve([]);
    });

    await waitFor(() => expect(lastSavedSectionText()).toBe(SECTION_TEXT));
  });

  test('saves never overlap, and the list refreshes only once the queue is empty', async () => {
    mockCreateBrief.mockImplementation(async (args: { content: SavedBrief }) => serverBrief(args.content));
    let inFlight = 0;
    let maxInFlight = 0;
    const events: string[] = [];
    mockUpdateBrief.mockImplementation(async (_id: string, args: { content: SavedBrief }) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      events.push('save');
      await new Promise((r) => setTimeout(r, 50));
      inFlight -= 1;
      return serverBrief(args.content);
    });
    const hook = renderRemoteBrief();
    await waitFor(() => expect(mockListMyBriefs).toHaveBeenCalled());
    mockListMyBriefs.mockImplementation(async () => {
      events.push('list');
      return [];
    });
    startBrief(hook);
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalledTimes(1));
    await researchFirstSection(hook);
    await waitFor(() => expect(lastSavedSectionText()).toBe(SECTION_TEXT));
    await waitFor(() => expect(events[events.length - 1]).toBe('list'));

    expect(maxInFlight).toBe(1);
    // A refresh never sits between two saves of one burst.
    for (let i = 1; i < events.length - 1; i++) {
      if (events[i] === 'list') expect(events[i + 1]).not.toBe('save');
    }
  });

  test('a failed save is reported and a save requested meanwhile still goes out', async () => {
    mockCreateBrief.mockImplementation(async (args: { content: SavedBrief }) => serverBrief(args.content));
    const hook = renderRemoteBrief();
    startBrief(hook);
    await waitFor(() => expect(mockCreateBrief).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockListMyBriefs.mock.calls.length).toBeGreaterThan(1));

    let failSave!: (e: Error) => void;
    mockUpdateBrief.mockImplementationOnce(
      () =>
        new Promise<RemoteBrief>((_resolve, reject) => {
          failSave = reject;
        }),
    );
    // A title edit starts a save that will fail; the section finishes while it runs.
    act(() => hook.result.current.setBriefTitle('Renamed'));
    await waitFor(() => expect(mockUpdateBrief).toHaveBeenCalledTimes(1));
    await researchFirstSection(hook);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 700)); // the autosave's debounce
      failSave(new Error('Network down'));
    });

    await waitFor(() => expect(hook.result.current.error).toBe('Network down'));
    await waitFor(() => expect(lastSavedSectionText()).toBe(SECTION_TEXT));
  });
});
