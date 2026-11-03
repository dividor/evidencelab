import { isLikelyNonAnswer, researchBriefSection, sectionPromptParts } from '../utils/briefStream';

// The section research prompt is written by the API from these parts
// (ui/backend/services/brief_section_prompt.py, tested in
// tests/unit/test_brief_section_prompt.py); the browser only collects them.

const OUTLINE = [
  { title: 'Context and scope', level: 1 },
  { title: 'What the evidence shows', level: 1, content: 'Cash transfers improved food consumption [1].' },
  { title: 'Effectiveness', level: 1 },
];

describe('sectionPromptParts', () => {
  test('a generated section sends its place in the outline and its guidance', () => {
    expect(
      sectionPromptParts({
        outline: OUTLINE,
        currentIndex: 2,
        briefTopic: 'cash transfers',
        briefInstructions: 'prioritise RCTs since 2018',
        context: 'emphasise rural areas',
        voiceInstructions: 'Plain English.',
      }),
    ).toEqual({
      outline: OUTLINE,
      current: 2,
      mode: 'generate',
      topic: 'cash transfers',
      instructions: 'prioritise RCTs since 2018',
      focus: 'emphasise rural areas',
      draft: undefined,
      instruction: undefined,
      published_after: undefined,
      voice_instructions: 'Plain English.',
    });
  });

  test('an update sends the current draft, its instruction and the date cutoff', () => {
    const parts = sectionPromptParts({
      outline: OUTLINE,
      currentIndex: 1,
      mode: 'update',
      existingContent: 'Enrolment rose sharply [1].',
      instruction: 'prioritise enforcement',
      publishedAfterIso: '2023-05-01T00:00:00.000Z',
    });
    expect(parts).toMatchObject({
      mode: 'update',
      draft: 'Enrolment rose sharply [1].',
      instruction: 'prioritise enforcement',
      published_after: '2023-05-01T00:00:00.000Z',
    });
  });

  test('a generated section never sends a draft', () => {
    const parts = sectionPromptParts({ outline: OUTLINE, currentIndex: 0, existingContent: 'old text' });
    expect(parts.draft).toBeUndefined();
  });

  test('empty parts are left out', () => {
    const parts = sectionPromptParts({
      outline: OUTLINE,
      currentIndex: 0,
      briefTopic: '',
      briefInstructions: null,
      voiceInstructions: '',
    });
    expect(JSON.parse(JSON.stringify(parts))).toEqual({ outline: OUTLINE, current: 0, mode: 'generate' });
  });
});

describe('researchBriefSection request', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  test('sends the heading as the question and a long draft as its own field', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'x' });
    global.fetch = fetchMock as unknown as typeof fetch;
    const draft = 'Attendance rose [1]. '.repeat(400);
    await researchBriefSection({
      apiBaseUrl: '/api',
      dataSource: 'wfp',
      heading: 'What the evidence shows',
      outline: OUTLINE,
      currentIndex: 1,
      mode: 'update',
      existingContent: draft,
      voiceInstructions: 'v'.repeat(6000),
      handlers: {
        onActivity: jest.fn(),
        onProgress: jest.fn(),
        onToken: jest.fn(),
        onSources: jest.fn(),
        onDone: jest.fn(),
        onError: jest.fn(),
      },
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    // The question stays short; the API's 5,000-character limit on it holds.
    expect(body.query).toBe('What the evidence shows');
    expect(body.brief_section.draft).toBe(draft);
    expect(body.brief_section.voice_instructions).toHaveLength(6000);
    expect(body.brief_section.current).toBe(1);
    expect(body.brief_section.outline).toEqual(OUTLINE);
  });
});

describe('isLikelyNonAnswer', () => {
  const SCOUT =
    "Alright, partner, I'm sendin' out a scout to rustle up some facts. Once that " +
    "information comes back, I'll be able to pen that section for ya.";

  test('flags short citationless narration when sources were read', () => {
    expect(isLikelyNonAnswer(SCOUT, 12)).toBe(true);
  });

  test('accepts real sections with citations', () => {
    expect(isLikelyNonAnswer('School meals improved attendance [1]. More [2].', 12)).toBe(false);
  });

  test('accepts substantial citationless text (e.g. a long intro)', () => {
    expect(isLikelyNonAnswer('x'.repeat(900), 12)).toBe(false);
  });

  test('does not flag when few sources were read', () => {
    expect(isLikelyNonAnswer(SCOUT, 0)).toBe(false);
  });

  test('flags empty content regardless', () => {
    expect(isLikelyNonAnswer('', 0)).toBe(true);
  });
});
