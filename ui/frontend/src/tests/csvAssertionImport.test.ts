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

const HEADER = 'Question,Unpacking Question / Probing';

describe('parseQaCsv', () => {
  test('maps the Question and Unpacking columns to query and expected answer', () => {
    const csv = [
      HEADER,
      'What changed after COVID?,Retrieve the most commonly cited changes.',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].query).toBe('What changed after COVID?');
    expect(rows[0].expectedAnswer).toBe('Retrieve the most commonly cited changes.');
  });

  test('accepts generic header aliases and parses tags/notes', () => {
    const csv = [
      'query,expected_answer,tags,notes',
      'How timely was WFP?,Respond in due time.,timeliness;covid,A note',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows[0].query).toBe('How timely was WFP?');
    expect(rows[0].expectedAnswer).toBe('Respond in due time.');
    expect(rows[0].tags).toEqual(['timeliness', 'covid']);
    expect(rows[0].notes).toBe('A note');
  });

  test('keeps quoted multi-line expected answers intact', () => {
    const csv = `${HEADER}\nQ1,"line one\n\nline two"`;
    const rows = parseQaCsv(csv);
    expect(rows[0].expectedAnswer).toContain('line one');
    expect(rows[0].expectedAnswer).toContain('line two');
  });

  test('drops rows without a question', () => {
    const csv = [
      HEADER,
      ',orphan expected answer',
      'Real question,Real expected',
    ].join('\n');
    const rows = parseQaCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].query).toBe('Real question');
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
    { query: 'Q1', expectedAnswer: 'E1' },
    { query: 'Q2', expectedAnswer: 'E2' },
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

  test('creates the dataset, a case per row, and the paired experiment', async () => {
    wireSuccess();
    const datasetId = await importDatasetWithExperiment({
      name: 'My set',
      dataSource: 'uneg',
      threshold: 0.7,
      rows,
    });
    expect(datasetId).toBe('ds1');

    const datasetCall = mockedAxios.post.mock.calls.find(([url]) =>
      /\/testing\/datasets$/.test(url as string),
    );
    expect(datasetCall?.[1]).toMatchObject({
      capability: 'ai_summary',
      data_source: 'uneg',
      name: 'My set',
    });

    const expCall = mockedAxios.post.mock.calls.find(([url]) =>
      (url as string).includes('/experiments'),
    );
    const body = expCall?.[1] as any;
    expect(body.dataset_id).toBe('ds1');
    expect(body.name).toBe('My set — LLM judge');
    expect(body.case_expectations.cases.c1.ovr).toEqual(['E1']);
    expect(body.case_expectations.cases.c2.ovr).toEqual(['E2']);
  });

  test('deletes the dataset and rethrows when case creation fails', async () => {
    mockedAxios.post.mockImplementation((url: string) => {
      if (url.includes('/cases')) return Promise.reject(new Error('boom'));
      return Promise.resolve({ data: { id: 'ds1' } });
    });
    mockedAxios.delete.mockResolvedValue({ data: {} });

    await expect(
      importDatasetWithExperiment({
        name: 'My set',
        dataSource: 'uneg',
        threshold: 0.7,
        rows,
      }),
    ).rejects.toThrow('boom');

    expect(mockedAxios.delete).toHaveBeenCalledWith(
      expect.stringContaining('/testing/datasets/ds1'),
    );
  });
});
