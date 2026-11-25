import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import type { RemoteBrief } from '../components/brief/briefTypes';
import type { SourceReference, SummaryModelConfig } from '../types/api';
import { useBrief } from '../components/brief/useBrief';

/**
 * A brief shared with the user is read-only, so opening it must never write
 * to it. Highlighting a cited excerpt (when its hover card opens, or in the
 * background pass that fills in missing highlights) used to store the
 * highlights on the owner's brief. The API lets only the owner write, so it
 * answered 404 and the page showed "Request failed with status code 404" on
 * opening a shared brief. The highlights are still shown, just not stored.
 */

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
  SEARCH_SEMANTIC_HIGHLIGHTS: true,
  SEMANTIC_HIGHLIGHT_THRESHOLD: 0.5,
}));
jest.mock('axios', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));
// The citation API double, with highlight stores logged (plain functions:
// CRA's jest config resets jest.fn implementations before each test).
jest.mock('../components/brief/briefCitationsApi', () => {
  const api = require('./helpers/fakeBriefCitations').fakeCitationsApi();
  const highlightStores: string[] = [];
  return {
    ...api,
    highlightStores,
    setHighlights: async (id: string, highlights: unknown) => {
      highlightStores.push(id);
      return api.setHighlights(id, highlights);
    },
  };
});
// The highlighter calls a model; here every cited source gets one match.
jest.mock('../components/brief/briefHighlights', () => {
  const matched = (source: { text?: string }) => ({
    ...source,
    claimMatches: [{ claim: 'cash helped', matches: [{ start: 0, end: 7 }] }],
  });
  return {
    ...jest.requireActual('../components/brief/briefHighlights'),
    highlightOneSource: async ({ source }: { source: { text?: string } }) => matched(source),
    highlightSectionSources: async ({ sources }: { sources: Array<{ text?: string }> }) =>
      sources.map(matched),
  };
});

const mockGetBrief = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  createBrief: jest.fn(),
  updateBrief: jest.fn(),
  getBrief: (...args: unknown[]) => mockGetBrief(...args),
  // A plain function: CRA resets jest.fn implementations before each test.
  listMyBriefs: async () => [],
  deleteBriefRemote: jest.fn(),
}));

const SOURCE: SourceReference = {
  chunkId: 'c1',
  docId: 'd1',
  title: 'Evaluation of school feeding',
  text: 'Cash transfers improved food consumption.',
  score: 0.9,
  index: 1,
  sourceId: 's1',
};
const MODEL: SummaryModelConfig = {
  model: 'nova-2-lite',
  max_tokens: 500,
  temperature: 0.2,
  chunk_overlap: 800,
  chunk_tokens_ratio: 0.5,
};

const brief = (canEdit: boolean): RemoteBrief => ({
  id: 'B',
  user_id: canEdit ? 'u-1' : 'owner-1',
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
    sourceCount: 1,
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
        currentRunId: null,
        renumbered: { content: 'Cash helped [1].', sources: [SOURCE], unresolved: [] },
      },
    ],
  },
  owner_name: canEdit ? null : 'Brief Owner',
  can_edit: canEdit,
  shared_with: [],
  created_at: '2026-11-20T10:00:00Z',
  updated_at: '2026-11-20T10:00:00Z',
});

const highlightStores = (): string[] =>
  (jest.requireMock('../components/brief/briefCitationsApi') as { highlightStores: string[] })
    .highlightStores;

const openAndHighlight = async (canEdit: boolean) => {
  mockGetBrief.mockImplementation(async () => brief(canEdit));
  const hook = renderHook(() =>
    useBrief({
      apiBaseUrl: '/api',
      dataSource: 'wfp',
      userKey: 'u-1',
      remote: true,
      semanticModelConfig: MODEL,
    }),
  );
  await act(async () => {
    hook.result.current.openBriefById('B');
  });
  await waitFor(() => expect(hook.result.current.briefTitle).toBe('Evidence brief'));
  // Opening the citation's hover card highlights its excerpt.
  await act(async () => {
    hook.result.current.requestSourceHighlight('B-s1', 'c1');
    await new Promise((r) => setTimeout(r, 50));
  });
  return hook;
};

beforeEach(() => {
  highlightStores().length = 0;
  (axios.get as jest.Mock).mockResolvedValue({ data: [] });
  (axios.post as jest.Mock).mockResolvedValue({ data: {} });
});

test('a brief shared with the user shows highlights but never stores them', async () => {
  const hook = await openAndHighlight(false);

  await waitFor(() =>
    expect(hook.result.current.sections[0].sources[0].claimMatches).toHaveLength(1),
  );
  expect(hook.result.current.canEdit).toBe(false);
  expect(highlightStores()).toEqual([]);
  expect(hook.result.current.error).toBeFalsy();
});

test("the user's own brief stores the highlights", async () => {
  await openAndHighlight(true);

  await waitFor(() => expect(highlightStores()).toContain('B'));
});
