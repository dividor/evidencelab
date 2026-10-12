import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import {
  BRIEF_INTRO,
  extraHeadingLines,
  researchOrder,
  sectionTargetWords,
  subSectionTitles,
} from '../components/brief/briefIntro';
import { introHeadingNote, introRerunNote, useBrief } from '../components/brief/useBrief';
import { streamAssistantChat } from '../utils/assistantStream';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: false,
}));
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockResearchSection = jest.fn();
const mockRequestRevise = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/briefStream'),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
  requestBriefRevise: (...args: unknown[]) => mockRequestRevise(...args),
}));

const INTRO = 'Education outcomes';
const SUBS = ['Enrolment and attendance', 'Learning outcomes'];
const LEAF = 'Costs';
const OUTLINE = [
  { id: 'a', title: INTRO, level: 1 },
  { id: 'a1', title: SUBS[0], level: 2 },
  { id: 'a2', title: SUBS[1], level: 2 },
  { id: 'b', title: LEAF, level: 1 },
];

const source = { chunkId: 'c1', docId: 'd1', title: 'Doc', text: 'x', score: 0.5, page: 1, index: 1 };
const CLEAN = `## ${INTRO}\n\nSchool feeding touches several education outcomes [1]. The sub-sections examine enrolment and learning.`;
const WITH_HEADINGS = `${CLEAN}\n\n### Enrolment\n\nEnrolment rose by 12% in Kenya [1].`;

// Each call answers with the next text in `texts` (the last one repeats).
const answersInTurn = (texts: string[]) => {
  let call = 0;
  return async ({ handlers }: { handlers: { onSources: Function; onDone: Function } }) => {
    const content = texts[Math.min(call, texts.length - 1)];
    call += 1;
    handlers.onSources([source]);
    handlers.onDone({ content, sources: [source] });
  };
};

describe('briefIntro helpers', () => {
  test('a top-level heading introduces the sub-headings that follow it', () => {
    expect(subSectionTitles(OUTLINE, 'a')).toEqual(SUBS);
    expect(subSectionTitles(OUTLINE, 'a1')).toEqual([]);
    expect(subSectionTitles(OUTLINE, 'b')).toEqual([]);
    expect(subSectionTitles(OUTLINE, 'missing')).toEqual([]);
  });

  test("the section's own length wins, then the introduction length, never longer than the brief's", () => {
    expect(sectionTargetWords(500, SUBS, 350, 120)).toBe(500);
    expect(sectionTargetWords(null, SUBS, 350, 120)).toBe(120);
    expect(sectionTargetWords(undefined, SUBS, null, 120)).toBe(120);
    expect(sectionTargetWords(null, SUBS, 100, 120)).toBe(100);
    expect(sectionTargetWords(null, [], 350, 120)).toBe(350);
    expect(sectionTargetWords(null, [], null, 120)).toBeNull();
  });

  test('the introduction length and re-runs come from config.json', () => {
    expect(BRIEF_INTRO).toEqual({ target_words: 120, heading_retries: 1 });
  });

  test('only headings after a leading title heading count as extra', () => {
    expect(extraHeadingLines(CLEAN)).toEqual([]);
    expect(extraHeadingLines(WITH_HEADINGS)).toEqual(['### Enrolment']);
    expect(extraHeadingLines('Intro text.\n\n## A heading\n\nMore.')).toEqual(['## A heading']);
    expect(extraHeadingLines('#hashtag is not a heading')).toEqual([]);
    expect(extraHeadingLines('')).toEqual([]);
  });

  test('a whole-brief run writes sub-sections before their introduction', () => {
    expect(researchOrder(OUTLINE)).toEqual(['a1', 'a2', 'a', 'b']);
    expect(
      researchOrder([
        { id: 'x', title: 'Orphan', level: 2 },
        { id: 'y', title: 'Top', level: 1 },
      ]),
    ).toEqual(['x', 'y']);
  });

  test('the Log note says how many headings remain and after how many re-runs', () => {
    expect(introHeadingNote(1, 1)).toBe(
      'This introduction still has 1 heading of its own after 1 re-run. Edit them out, or use AI Regenerate.',
    );
    expect(introHeadingNote(2, 3)).toMatch(/2 headings of its own after 3 re-runs/);
  });
});

describe('introduction requests', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const captureFetchBody = async (run: () => Promise<unknown>) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}), text: async () => '' });
    global.fetch = fetchMock as unknown as typeof fetch;
    try {
      await run();
    } catch {
      // the fake response fails; only the request matters here
    }
    return JSON.parse(fetchMock.mock.calls[0][1].body);
  };

  const handlers = {
    onPhase: jest.fn(), onPlan: jest.fn(), onSearchStatus: jest.fn(), onToken: jest.fn(),
    onSources: jest.fn(), onDone: jest.fn(), onError: jest.fn(),
  };

  test('research sends the sub-headings, and omits the field otherwise', async () => {
    const withSubs = await captureFetchBody(() =>
      streamAssistantChat({ apiBaseUrl: '/api', query: 'q', deepResearch: true, introducesSubSections: SUBS, handlers } as any),
    );
    const without = await captureFetchBody(() =>
      streamAssistantChat({ apiBaseUrl: '/api', query: 'q', deepResearch: true, handlers } as any),
    );
    expect(withSubs.introduces_sub_sections).toEqual(SUBS);
    expect(without).not.toHaveProperty('introduces_sub_sections');
  });
});

describe('useBrief introduction sections', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    // CRA resets mock implementations before each test; re-arm the activity post.
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    mockResearchSection.mockImplementation(answersInTurn([CLEAN]));
    mockRequestRevise.mockResolvedValue(CLEAN);
  });

  const briefWithIntro = () => {
    const hook = renderHook(() => useBrief({ apiBaseUrl: '/api', dataSource: 'wfp' }));
    act(() => {
      hook.result.current.startFromTemplate('School feeding', [
        { title: INTRO, sub: false },
        { title: SUBS[0], sub: true },
        { title: SUBS[1], sub: true },
        { title: LEAF, sub: false },
      ]);
    });
    return hook;
  };
  const idOf = (hook: ReturnType<typeof briefWithIntro>, title: string) =>
    hook.result.current.sections.find((s) => s.title === title)!.id;
  const callFor = (title: string) =>
    mockResearchSection.mock.calls.map(([args]) => args).filter((a) => a.heading === title);

  test('an introduction is researched with its sub-headings at the introduction length', async () => {
    const hook = briefWithIntro();
    act(() => hook.result.current.setTargetWords(350));
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    const [intro] = callFor(INTRO);
    expect(intro.introducesSubSections).toEqual(SUBS);
    expect(intro.targetWords).toBe(BRIEF_INTRO.target_words);
  });

  test('sub-sections and other top-level sections are unchanged', async () => {
    const hook = briefWithIntro();
    act(() => hook.result.current.setTargetWords(350));
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, SUBS[0]), null);
      await hook.result.current.regenerate(idOf(hook, LEAF), null);
    });
    for (const title of [SUBS[0], LEAF]) {
      const [call] = callFor(title);
      expect(call.introducesSubSections).toBeNull();
      expect(call.targetWords).toBe(350);
    }
  });

  test('an introduction that comes back with headings is re-run, and kept once it has none', async () => {
    mockResearchSection.mockImplementation(answersInTurn([WITH_HEADINGS, CLEAN]));
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    expect(callFor(INTRO)).toHaveLength(2);
    const intro = hook.result.current.sections.find((s) => s.title === INTRO)!;
    expect(intro.content).toBe(CLEAN);
    expect(intro.introHeadingWarning).toBeUndefined();
    expect(intro.audit).toHaveLength(1);
    expect(intro.audit?.[0]?.note).toBe(introRerunNote(1));
    expect(intro.activity.some((a) => /came back with 1 heading; re-running \(1 of 1\)/.test(a.text))).toBe(true);
  });

  test('after its last re-run an introduction with headings is kept, with a warning and a Log note', async () => {
    mockResearchSection.mockImplementation(answersInTurn([WITH_HEADINGS]));
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    expect(callFor(INTRO)).toHaveLength(1 + BRIEF_INTRO.heading_retries);
    const intro = hook.result.current.sections.find((s) => s.title === INTRO)!;
    expect(intro.status).toBe('done');
    expect(intro.content).toBe(WITH_HEADINGS);
    expect(intro.introHeadingWarning).toBe(1);
    expect(intro.audit?.slice(-1)[0]?.note).toBe(introHeadingNote(1, BRIEF_INTRO.heading_retries));
  });

  test('a restated title heading alone does not trigger a re-run', async () => {
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    expect(callFor(INTRO)).toHaveLength(1);
  });

  test('a leaf section with headings is not re-run', async () => {
    mockResearchSection.mockImplementation(answersInTurn([WITH_HEADINGS]));
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, LEAF), null);
    });
    expect(callFor(LEAF)).toHaveLength(1);
    expect(hook.result.current.sections.find((s) => s.title === LEAF)!.introHeadingWarning).toBeUndefined();
  });

  test('a whole-brief run writes each introduction after its sub-sections', async () => {
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.startResearch();
    });
    expect(mockResearchSection.mock.calls.map(([args]) => args.heading)).toEqual([SUBS[0], SUBS[1], INTRO, LEAF]);
  });

  test('AI Edit on an introduction tells the revise request its sub-headings, and flags headings it leaves', async () => {
    mockRequestRevise.mockResolvedValue(WITH_HEADINGS);
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    await act(async () => {
      await hook.result.current.reviseSection(idOf(hook, INTRO), 'edit', 'Shorten it');
    });
    expect(mockRequestRevise.mock.calls.slice(-1)[0][0].introducesSubSections).toEqual(SUBS);
    await waitFor(() =>
      expect(hook.result.current.sections.find((s) => s.title === INTRO)!.introHeadingWarning).toBe(1),
    );
  });

  test('the warning is saved with the brief', async () => {
    mockResearchSection.mockImplementation(answersInTurn([WITH_HEADINGS]));
    const hook = briefWithIntro();
    await act(async () => {
      await hook.result.current.regenerate(idOf(hook, INTRO), null);
    });
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem('evidencelab_brief_history_v1') || '[]');
      expect(saved[0]?.sections?.[0]?.introHeadingWarning).toBe(1);
    });
  });
});
