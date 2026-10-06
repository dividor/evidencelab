import {
  DocumentSections,
  SummaryConfigDefaults,
  methodForMode,
  resolveSummarySettings,
  selectedChars,
} from '../components/documents/summary/summarySettings';
import {
  SummaryGenerationError,
  generateDocumentSummary,
} from '../components/documents/summary/documentSummaryApi';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));

const ALL = ['executive_summary', 'findings', 'annexes'];
const CONFIG: SummaryConfigDefaults = {
  prompt: 'OUTPUT FORMAT: the default prompt',
  modes: ['map_reduce', 'single_prompt'],
  all_section_types: ALL,
  mode: 'map_reduce',
  section_types: ['executive_summary', 'findings'],
  single_prompt_context_window: 400000,
};

describe('resolveSummarySettings', () => {
  test('uses the data source config when the team sets nothing', () => {
    expect(resolveSummarySettings(CONFIG, null)).toEqual({
      mode: 'map_reduce',
      sectionTypes: ['executive_summary', 'findings'],
      prompt: CONFIG.prompt,
    });
  });

  test('team defaults win over config', () => {
    expect(
      resolveSummarySettings(CONFIG, {
        docSummaryMode: 'single_prompt',
        docSummarySectionTypes: ['findings'],
        docSummaryPrompt: 'Three bullet points.',
      }),
    ).toEqual({ mode: 'single_prompt', sectionTypes: ['findings'], prompt: 'Three bullet points.' });
  });

  test('ignores team values that are not valid', () => {
    expect(
      resolveSummarySettings(CONFIG, {
        docSummaryMode: 'fastest',
        docSummarySectionTypes: ['chapter_one'],
        docSummaryPrompt: '   ',
      }),
    ).toEqual(resolveSummarySettings(CONFIG, null));
  });

  test('every section type when config names none', () => {
    const { section_types: _unused, ...noSections } = CONFIG;
    expect(resolveSummarySettings(noSections, null).sectionTypes).toEqual(ALL);
  });

  test('a summary saved as generated keeps its mode', () => {
    expect(methodForMode('single_prompt')).toBe('ui_single_prompt');
    expect(methodForMode('map_reduce')).toBe('ui_map_reduce');
  });
});

const SECTIONS: DocumentSections = {
  has_section_types: true,
  sections: [
    { section_type: 'executive_summary', chars: 20000, chunks: 10 },
    { section_type: 'findings', chars: 200000, chunks: 100 },
  ],
  single_prompt: { context_window: 1048576, available: true, reason: null },
};

describe('selected text size', () => {
  test('counts the chosen sections only', () => {
    expect(selectedChars(SECTIONS, ['executive_summary'])).toBe(20000);
    expect(selectedChars(SECTIONS, ['executive_summary', 'findings'])).toBe(220000);
  });

  test('an untagged document counts all its text', () => {
    expect(selectedChars({ ...SECTIONS, has_section_types: false }, [])).toBe(220000);
  });
});

const streamOf = (chunks: string[]) => {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    getReader: () => ({
      read: async () =>
        i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { value: undefined, done: true },
    }),
  };
};

const frame = (data: object) => `data: ${JSON.stringify(data)}\n\n`;
const SETTINGS = { mode: 'map_reduce' as const, sectionTypes: ['findings'], prompt: 'Summarise.' };
const MODEL = { model: 'gemini-2.5-flash', max_tokens: 2000, temperature: 0.2, chunk_overlap: 800, chunk_tokens_ratio: 0.5 };

describe('generateDocumentSummary', () => {
  const fetchMock = jest.fn();
  beforeEach(() => {
    (global as any).fetch = fetchMock;
  });

  test('posts the settings and reads progress then the summary, across split chunks', async () => {
    const done = frame({ type: 'done', summary: 'The summary.', mode: 'map_reduce', method: 'ui_map_reduce', calls: 3 });
    fetchMock.mockResolvedValue({
      ok: true,
      body: streamOf([
        frame({ type: 'meta', has_section_types: true }) + frame({ type: 'progress', stage: 'map', done: 1, total: 2 }),
        done.slice(0, 20),
        done.slice(20),
      ]),
    });
    const onProgress = jest.fn();
    const onMeta = jest.fn();

    const result = await generateDocumentSummary({
      dataSource: 'wfp',
      docId: 'doc 7',
      settings: SETTINGS,
      model: MODEL,
      onProgress,
      onMeta,
    });

    expect(result).toMatchObject({ summary: 'The summary.', method: 'ui_map_reduce', calls: 3 });
    expect(onMeta).toHaveBeenCalledWith({ has_section_types: true });
    expect(onProgress).toHaveBeenCalledWith({ stage: 'map', done: 1, total: 2 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/document-summaries/doc%207/generate');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.credentials).toBe('include');
    expect(JSON.parse(init.body)).toEqual({
      data_source: 'wfp',
      mode: 'map_reduce',
      section_types: ['findings'],
      prompt: 'Summarise.',
      summary_model: { model: 'gemini-2.5-flash', max_tokens: 2000, temperature: 0.2 },
    });
  });

  test('an error frame rejects with its message', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      body: streamOf([frame({ type: 'error', error: 'Choose fewer sections.' })]),
    });
    await expect(
      generateDocumentSummary({ dataSource: 'wfp', docId: 'd', settings: SETTINGS, model: MODEL }),
    ).rejects.toEqual(new SummaryGenerationError('Choose fewer sections.'));
  });

  test('a refused request rejects with the server detail', async () => {
    fetchMock.mockResolvedValue({ ok: false, body: null, json: async () => ({ detail: 'Unknown summarization model' }) });
    await expect(
      generateDocumentSummary({ dataSource: 'wfp', docId: 'd', settings: SETTINGS, model: MODEL }),
    ).rejects.toThrow('Unknown summarization model');
  });

  test('a stream that ends without a summary is an error', async () => {
    fetchMock.mockResolvedValue({ ok: true, body: streamOf([frame({ type: 'meta', has_section_types: true })]) });
    await expect(
      generateDocumentSummary({ dataSource: 'wfp', docId: 'd', settings: SETTINGS, model: MODEL }),
    ).rejects.toThrow('could not be generated');
  });
});
