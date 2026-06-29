import axios from 'axios';
import { parseQaCsv } from '../components/admin/testing/csv';
import {
  DEFAULT_RUBRIC,
  buildJudgeMatrix,
  importDatasetWithExperiment,
} from '../components/admin/testing/experimentImport';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const HEADER = 'query,tags,notes,filters,expectation';
const NAME = 'My set';
const SOURCE = 'uneg';
const EXP_PATH = '/experiments';
const CAP = 'ai_summary';

describe('parseQaCsv', () => {
  test('mirrors the regular dataset columns plus an expectation column', () => {
    const csv = [
      HEADER,
      'What changed after COVID?,covid;baseline,A note,,Retrieve the cited changes.',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].input).toEqual({ query: 'What changed after COVID?' });
    expect(rows[0].tags).toEqual(['covid', 'baseline']);
    expect(rows[0].notes).toBe('A note');
    expect(rows[0].expectation).toBe('Retrieve the cited changes.');
  });

  test('parses a filters JSON column into the case input', () => {
    const csv = [
      HEADER,
      'nutrition outcomes,,,"{""country"": ""Kenya""}",Expected text',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows[0].input).toEqual({
      query: 'nutrition outcomes',
      filters: { country: 'Kenya' },
    });
    expect(rows[0].expectation).toBe('Expected text');
  });

  test('accepts header aliases (question / expected_answer)', () => {
    const csv = [
      'question,expected_answer',
      'How timely was WFP?,Respond in due time.',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows[0].input).toEqual({ query: 'How timely was WFP?' });
    expect(rows[0].expectation).toBe('Respond in due time.');
  });

  test('keeps quoted multi-line expectations intact', () => {
    const csv = `${HEADER}\nQ1,,,,"line one\n\nline two"`;
    const rows = parseQaCsv(csv);
    expect(rows[0].expectation).toContain('line one');
    expect(rows[0].expectation).toContain('line two');
  });

  test('drops rows without a query', () => {
    const csv = [HEADER, ',,,,orphan expectation', 'Real question,,,,Real'].join(
      '\n',
    );
    const rows = parseQaCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].input).toEqual({ query: 'Real question' });
  });
});

describe('buildJudgeMatrix', () => {
  test('creates one llm_judge column with each row overriding its rubric', () => {
    const matrix = buildJudgeMatrix(
      [
        { caseId: 'c1', expectedAnswer: 'answer one' },
        { caseId: 'c2', expectedAnswer: 'answer two' },
      ],
      0.7,
    );
    expect(matrix.columns).toEqual([
      { type: 'llm_judge', rubric: DEFAULT_RUBRIC, threshold: 0.7 },
    ]);
    expect(matrix.cases.c1).toEqual({
      active: true,
      cols: [true],
      ovr: ['answer one'],
    });
    expect(matrix.cases.c2.ovr).toEqual(['answer two']);
  });
});

describe('importDatasetWithExperiment', () => {
  const rows = [
    { input: { query: 'Q1' }, expectation: 'E1' },
    { input: { query: 'Q2' }, expectation: 'E2' },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
  });

  const wireSuccess = () => {
    let caseCount = 0;
    mockedAxios.post.mockImplementation((url: string) => {
      if (url.includes('/cases')) {
        caseCount += 1;
        return Promise.resolve({ data: { id: `c${caseCount}` } });
      }
      if (url.includes('/experiments')) {
        return Promise.resolve({ data: { id: 'e1' } });
      }
      return Promise.resolve({ data: { id: 'ds1' } });
    });
  };

  test('names dataset/experiment with suffixes and pairs expectations', async () => {
    wireSuccess();
    const datasetId = await importDatasetWithExperiment({
      name: NAME,
      capability: CAP,
      dataSource: SOURCE,
      threshold: 0.7,
      rows,
    });
    expect(datasetId).toBe('ds1');

    const datasetCall = mockedAxios.post.mock.calls.find(([url]) =>
      /\/testing\/datasets$/.test(url as string),
    );
    expect(datasetCall?.[1]).toMatchObject({
      capability: CAP,
      data_source: 'uneg',
      name: 'My set_dataset',
    });

    const caseCall = mockedAxios.post.mock.calls.find(([url]) =>
      (url as string).includes('/cases'),
    );
    expect(caseCall?.[1]).toMatchObject({ input: { query: 'Q1' } });

    const expCall = mockedAxios.post.mock.calls.find(([url]) =>
      (url as string).includes(EXP_PATH),
    );
    const body = expCall?.[1] as any;
    expect(body.name).toBe('My set_experiment');
    expect(body.case_expectations.cases.c1.ovr).toEqual(['E1']);
    expect(body.case_expectations.cases.c2.ovr).toEqual(['E2']);
  });

  test('passes model_combo / group_id config through to the experiment', async () => {
    wireSuccess();
    await importDatasetWithExperiment({
      name: NAME,
      capability: CAP,
      dataSource: SOURCE,
      threshold: 0.7,
      config: { model_combo: 'Azure Foundry', group_id: 'g1' },
      rows,
    });
    const expCall = mockedAxios.post.mock.calls.find(([url]) =>
      (url as string).includes(EXP_PATH),
    );
    expect((expCall?.[1] as any).config).toEqual({
      model_combo: 'Azure Foundry',
      group_id: 'g1',
    });
  });

  test('sends null config when none is supplied', async () => {
    wireSuccess();
    await importDatasetWithExperiment({
      name: NAME,
      capability: CAP,
      dataSource: SOURCE,
      threshold: 0.7,
      config: {},
      rows,
    });
    const expCall = mockedAxios.post.mock.calls.find(([url]) =>
      (url as string).includes(EXP_PATH),
    );
    expect((expCall?.[1] as any).config).toBeNull();
  });

  test('deletes the dataset and rethrows when case creation fails', async () => {
    mockedAxios.post.mockImplementation((url: string) => {
      if (url.includes('/cases')) return Promise.reject(new Error('boom'));
      return Promise.resolve({ data: { id: 'ds1' } });
    });
    mockedAxios.delete.mockResolvedValue({ data: {} });

    await expect(
      importDatasetWithExperiment({
        name: NAME,
        capability: CAP,
        dataSource: SOURCE,
        threshold: 0.7,
        rows,
      }),
    ).rejects.toThrow('boom');

    expect(mockedAxios.delete).toHaveBeenCalledWith(
      expect.stringContaining('/testing/datasets/ds1'),
    );
  });
});
