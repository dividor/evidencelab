import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import type { RemoteBrief } from '../components/brief/briefTypes';
import { errorText } from '../components/brief/briefErrors';
import { useBrief } from '../components/brief/useBrief';

/**
 * Keep Edits and Reject Edits on a section's change awaiting review. Until
 * the API answers, the page still holds the change as awaiting review, so a
 * second click used to send the same Keep again; the API refused it ("This
 * change is no longer awaiting review") and the page showed "Request failed
 * with status code 400". Now one decision per section is on its way at a
 * time, and a refusal shows the API's own reason.
 */

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
  SEARCH_SEMANTIC_HIGHLIGHTS: false,
  SEMANTIC_HIGHLIGHT_THRESHOLD: 0.5,
}));
jest.mock('axios', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));
// Keep and Reject answer when the test says so (plain functions: CRA's jest
// config resets jest.fn implementations before each test).
jest.mock('../components/brief/briefCitationsApi', () => {
  const api = require('./helpers/fakeBriefCitations').fakeCitationsApi();
  const review = {
    calls: [] as string[],
    answer: (): Promise<unknown> => Promise.reject(new Error('no answer set')),
  };
  const decide = (type: string) => async (_id: string, sectionId: string, runId: string) => {
    review.calls.push(`${type} ${sectionId} ${runId}`);
    return review.answer();
  };
  return { ...api, review, keepRun: decide('keep'), rejectRun: decide('reject') };
});

const mockGetBrief = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: jest.fn(),
  updateBrief: jest.fn(),
  getBrief: (...args: unknown[]) => mockGetBrief(...args),
  listMyBriefs: async () => [],
  deleteBriefRemote: jest.fn(),
}));

const KEEP_SENT = 'keep B-s1 r2';
const NOT_AWAITING = 'This change is no longer awaiting review';
const SAVE_FAILED = 'Could not save the brief.';

const review = (): { calls: string[]; answer: () => Promise<unknown> } =>
  (jest.requireMock('../components/brief/briefCitationsApi') as {
    review: { calls: string[]; answer: () => Promise<unknown> };
  }).review;

// The user's own brief, its one section with an AI edit (r2) awaiting review.
const brief = (awaiting: boolean): RemoteBrief => ({
  id: 'B',
  user_id: 'u-1',
  title: 'Evidence brief',
  query: 'cash',
  data_source: 'wfp',
  voice_profile_id: null,
  content: {
    id: 'B',
    title: 'Evidence brief',
    query: 'cash',
    date: 1,
    sectionCount: 1,
    sourceCount: 0,
    referenceGrouping: 'passage',
    references: [],
    referenceGroups: [],
    sections: [
      {
        id: 'B-s1',
        title: 'Findings',
        level: 1,
        status: 'done',
        runs: [],
        currentRunId: 'r2',
        pendingReview: awaiting
          ? { runId: 'r2', baseRunId: 'r1', kind: 'edit', at: 1, before: 'Old words.' }
          : null,
        renumbered: { content: 'New words.', sources: [], unresolved: [] },
      },
    ],
  },
  owner_name: null,
  can_edit: true,
  shared_with: [],
  created_at: '2026-11-21T10:00:00Z',
  updated_at: '2026-11-21T10:00:00Z',
});

const openAwaitingReview = async () => {
  mockGetBrief.mockImplementation(async () => brief(true));
  const hook = renderHook(() =>
    useBrief({ apiBaseUrl: '/api', dataSource: 'wfp', userKey: 'u-1', remote: true }),
  );
  await act(async () => {
    hook.result.current.openBriefById('B');
  });
  await waitFor(() => expect(hook.result.current.sections[0]?.pendingReview?.runId).toBe('r2'));
  return hook;
};

// An answer the test releases, to look at the page while the request is out.
const held = () => {
  let release: (value: unknown) => void = () => {};
  const answer = new Promise((resolve) => {
    release = resolve;
  });
  return { answer, release };
};

beforeEach(() => {
  review().calls.length = 0;
  (axios.get as jest.Mock).mockResolvedValue({ data: [] });
  (axios.post as jest.Mock).mockResolvedValue({ data: {} });
});

test('a second Keep while the first is on its way sends nothing', async () => {
  const hook = await openAwaitingReview();
  const keep = held();
  review().answer = () => keep.answer;

  await act(async () => {
    void hook.result.current.dismissChanges('B-s1');
    void hook.result.current.dismissChanges('B-s1');
  });

  await waitFor(() => expect(review().calls).toEqual([KEEP_SENT]));
  expect(hook.result.current.isReviewBusy('B-s1')).toBe(true);

  await act(async () => {
    keep.release(brief(false));
  });

  await waitFor(() => expect(hook.result.current.isReviewBusy('B-s1')).toBe(false));
  expect(hook.result.current.sections[0].pendingReview).toBeNull();
  expect(review().calls).toEqual([KEEP_SENT]);
  expect(hook.result.current.error).toBeFalsy();
});

test('Reject sends nothing while a Keep is on its way', async () => {
  const hook = await openAwaitingReview();
  const keep = held();
  review().answer = () => keep.answer;

  await act(async () => {
    void hook.result.current.dismissChanges('B-s1');
    void hook.result.current.rejectChanges('B-s1');
  });
  await act(async () => {
    keep.release(brief(false));
  });

  await waitFor(() => expect(hook.result.current.isReviewBusy('B-s1')).toBe(false));
  expect(review().calls).toEqual([KEEP_SENT]);
});

test("a refused Keep shows the API's reason and frees the buttons", async () => {
  const hook = await openAwaitingReview();
  review().answer = () =>
    Promise.reject(
      Object.assign(new Error('Request failed with status code 400'), {
        response: { status: 400, data: { detail: NOT_AWAITING } },
      }),
    );

  await act(async () => {
    await hook.result.current.dismissChanges('B-s1');
  });

  expect(hook.result.current.error).toBe(NOT_AWAITING);
  expect(hook.result.current.isReviewBusy('B-s1')).toBe(false);
});

describe('errorText', () => {
  test("gives the API's reason over axios' status message", () => {
    const e = Object.assign(new Error('Request failed with status code 400'), {
      response: { data: { detail: NOT_AWAITING } },
    });
    expect(errorText(e, 'Could not keep the edits.')).toBe(NOT_AWAITING);
  });

  test("keeps the error's message when the API gave no reason as text", () => {
    const e = Object.assign(new Error('Request failed with status code 422'), {
      response: { data: { detail: [{ loc: ['body'], msg: 'field required' }] } },
    });
    expect(errorText(e, SAVE_FAILED)).toBe('Request failed with status code 422');
    expect(errorText(new Error('Network Error'), SAVE_FAILED)).toBe('Network Error');
  });

  test('uses the fallback for something that is not an error', () => {
    expect(errorText('boom', SAVE_FAILED)).toBe(SAVE_FAILED);
  });
});
