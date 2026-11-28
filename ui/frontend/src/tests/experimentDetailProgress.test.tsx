import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axios from 'axios';
import ExperimentDetail from '../components/admin/testing/ExperimentDetail';
import GeneratedSection from '../components/admin/testing/GeneratedSection';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const TS = '2026-06-25T16:58:28Z';

const runningDetail = {
  id: 'e1',
  dataset_id: 'd1',
  name: 'COVID eval',
  status: 'running',
  config: null,
  case_expectations: null,
  summary_stats: null,
  started_at: TS,
  finished_at: null,
  created_at: TS,
  runs: [
    {
      id: 'r1',
      experiment_id: 'e1',
      run_number: 4,
      status: 'running',
      summary_stats: { progress: { completed: 3, total: 5 } },
      started_at: TS,
      finished_at: null,
      created_at: TS,
      results: [],
    },
  ],
};

const completedDetail = {
  ...runningDetail,
  status: 'completed',
  runs: [
    {
      ...runningDetail.runs[0],
      status: 'completed',
      summary_stats: {
        total: 5,
        passed: 5,
        failed: 0,
        errored: 0,
        pass_rate: 1,
        mean_score: 0.97,
        duration_ms: 1234,
      },
      finished_at: '2026-06-25T17:00:00Z',
      results: [],
    },
  ],
};

const mockGet = (detail: unknown) => {
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/groups')) return Promise.resolve({ data: [] });
    if (url.includes('/cases')) return Promise.resolve({ data: [] });
    if (url.includes('/testing/experiments/')) return Promise.resolve({ data: detail });
    return Promise.resolve({ data: [] });
  });
};

beforeEach(() => {
  jest.clearAllMocks();
});

const noop = () => undefined;

describe('ExperimentDetail run progress', () => {
  test('shows the running template section and the whole queue before any draft is saved', async () => {
    mockGet({ ...runningDetail, runs: [{ ...runningDetail.runs[0], summary_stats: {
      progress: {completed: 0, total: 2, remaining_sections: [{template: 'Review', heading: 'Costs'}, {template: 'Review', heading: 'Access'}]},
    } }] });
    render(<ExperimentDetail experimentId="e1" onBack={noop} onEdit={noop} />);
    expect(await screen.findByRole('row', { name: /Costs.*Review.*Running/ })).toBeVisible();
    expect(screen.getByRole('row', { name: /Access.*Review.*Queued/ })).toBeVisible();
  });

  test('explains why an editorial rejection has no generated section', () => {
    const reason = 'The opening does not identify the equipment being discussed.';
    render(<GeneratedSection result={{
      id: 'r', experiment_id: 'e', test_case_id: 'c', created_at: TS, status: 'fail',
      actual_output: { capability: 'brief', written: false, summary: '', editorial_issues: [reason] },
    }} />);
    fireEvent.click(screen.getByText('Generated section'));
    expect(screen.getByText('No section was written.')).toBeVisible();
    expect(screen.getByText(reason)).toBeVisible();
  });

  test('shows an already loaded saved draft even before claim details are available', async () => {
    const text = 'The inspection confirmed the equipment was operational [4].';
    const result = { id: 'saved', status: 'fail', actual_output: {
      capability: 'brief', written: true, summary: text, words: 8, assignment: { heading: 'Equipment status' },
    } };
    mockGet({ ...completedDetail, runs: [{ ...completedDetail.runs[0], results: [result] }] });
    render(<ExperimentDetail experimentId="e1" onBack={noop} onEdit={noop} />);
    fireEvent.click(await screen.findByText('Equipment status'));
    fireEvent.click(screen.getByText('Generated section'));
    expect(screen.getByText(text)).toBeVisible();
    expect(screen.queryByText('No section was written.')).toBeNull();
  });

  test('shows the saved brief below its query and names each grading criterion', async () => {
    const text = 'Technicians identified a pressure loss [4, 8].\n\nThe replacement held pressure [8].';
    const result = {
      id: 'res', status: 'pass', actual_output: {
        capability: 'brief', summary: text, written: true, words: 10,
        assignment: { topic: 'Equipment maintenance', heading: 'Inspection', target_words: 12 },
        sources: [{ index: 8, title: 'Service log', page: 37, headings: ['Operational records', 'Results'], text: 'Second inspection.' },
          { index: 4, title: 'First inspection', page: 2, text: 'Pressure reading.' }],
      },
      brief_evidence: {
        references: [{ label: '4', source_position: 1 }, { label: '8', source_position: 0 }],
        paragraphs: [
          [{ parts: [{ text: 'Technicians identified a pressure loss ' }, { text: '[4, 8]', marker: true }, { text: '.' }], references: [0, 1] }],
          [{ parts: [{ text: 'The replacement held pressure ' }, { text: '[8]', marker: true }, { text: '.' }], references: [1] }],
        ],
      },
      assertion_results: [
        { type: 'brief_factual', passed: false, score: 0.25, message: '', judge_prompt: 'Exact factual prompt',
          threshold: 1, claim_grades: [{ claim: 1, passed: false, score: 0.25, verdict: 'partially_supported', unmet: ['Original pressure is missing.'], supporting_quotes: [{citation: 4, quote: 'Pressure reading.'}], reason: 'The reading lacks a baseline.' },
            { claim: 2, passed: true, score: 1, reason: 'The log confirms the replacement held.' }],
          rubric: 'Check factual grounding against the cited excerpts. Check the numbers.' },
        { type: 'llm_judge', passed: true, factual_support: true, label: 'Historical factual grade', message: 'Original reasoning.', rubric: 'Check factual grounding against the cited excerpts.' },
        { type: 'llm_judge', passed: true, rubric: 'Read the brief topic together with its section heading. Check the population.' },
        { type: 'llm_judge', passed: true, label: 'Test conditions', message: 'The log documents “held pressure”.', quoted_claims: [1], rubric: 'Verify the temperature.' },
        { type: 'llm_judge', passed: true, rubric: 'Does the draft specify the units? Check the pressure.' },
      ],
    };
    mockGet({ ...completedDetail, runs: [{ ...completedDetail.runs[0], results: [result] }] });
    render(<ExperimentDetail experimentId="e1" onBack={noop} onEdit={noop} />);
    fireEvent.click(await screen.findByText('Inspection'));
    const panel = screen.getByText('Generated section').closest('details')!;
    expect(panel).not.toHaveAttribute('open');
    expect(panel.previousElementSibling).toContainElement(screen.getByText('Equipment maintenance'));
    expect(panel.nextElementSibling).toContainElement(screen.getByText('Expectations'));
    fireEvent.click(within(panel).getByText('Generated section'));
    expect(panel).toHaveAttribute('open');
    const paragraphs = panel.querySelectorAll('.testing-claim-paragraph');
    expect(Array.from(paragraphs, node => node.textContent).join('\n\n')).toBe(text);
    const firstClaim = within(panel).getByRole('button', { name: 'Show cited passages [4, 8]' });
    expect(firstClaim).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(firstClaim);
    const passages = within(panel).getByRole('group', { name: 'Cited passages for this claim' });
    expect(within(passages).getByText('Pressure reading.')).toBeVisible();
    expect(within(passages).getByText('Second inspection.')).toBeVisible();
    expect(within(passages).getByText('Operational records › Results')).toBeVisible();
    fireEvent.click(firstClaim);
    expect(passages).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'Show cited passages [8]' }));
    const secondPassage = within(panel).getByRole('group', { name: 'Cited passages for this claim' });
    expect(within(secondPassage).queryByText('Pressure reading.')).toBeNull();
    expect(within(secondPassage).getByText('Second inspection.')).toBeVisible();
    const references = panel.querySelectorAll('details');
    expect(references).toHaveLength(2);
    expect(references[0]).not.toHaveAttribute('open');
    expect(references[1]).not.toHaveAttribute('open');
    fireEvent.click(within(references[0]).getByText('[4] First inspection · p. 2'));
    expect(within(references[0]).getByText('Pressure reading.')).toBeVisible();
    expect(references[1]).not.toHaveAttribute('open');
    expect(screen.getByText('Factual support from citations')).toBeInTheDocument();
    expect(screen.getByText('Relevance to the assigned topic and heading')).toBeInTheDocument();
    expect(screen.getByText('Test conditions')).toBeInTheDocument();
    expect(screen.getByText('Does the draft specify the units?')).toBeInTheDocument();
    expect(screen.queryByText('llm_judge')).not.toBeInTheDocument();
    const assessment = screen.getByText('Factual support from citations').closest('details')!;
    expect(assessment).not.toHaveAttribute('open');
    fireEvent.click(within(assessment).getByText('Factual support from citations'));
    await within(assessment).findByText('Claim 1');
    const first = assessment.querySelectorAll('.testing-evidence-claim')[0] as HTMLElement;
    expect(within(first).getByText('Fail')).toBeVisible();
    expect(within(first).getByText('Score 0.25')).toBeVisible();
    expect(within(first).getByText('Partially supported')).toBeVisible();
    expect(within(first).getByText('Required 1.00')).toBeVisible();
    expect(within(first).getByText('Original pressure is missing.')).toBeVisible();
    expect(within(first).queryByText('Supporting evidence')).toBeNull();
    expect(within(first).getAllByRole('list')).toHaveLength(1);
    const firstReference = within(first).getByText('[4] First inspection · p. 2');
    expect(firstReference.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(firstReference);
    expect(within(first).getByText('Pressure reading.')).toBeVisible();
    expect(first).toHaveTextContent('The reading lacks a baseline.');
    expect(within(assessment).getByText('Grading criterion').closest('details')).not.toHaveAttribute('open');
    const body = assessment.querySelector('.testing-assertion-body')!;
    expect(body.lastElementChild).toHaveTextContent('Full prompt sent to the LLM');
    expect(body.lastElementChild?.previousElementSibling).toHaveTextContent('Grading criterion');
    expect(within(assessment).getByText('Claim 2')).toBeVisible();
    const quotedClaim = within(assessment).getByText('Claim 2').closest('.testing-evidence-claim')! as HTMLElement;
    const passage = within(quotedClaim).getByText('[8] Service log · p. 37').closest('details')!;
    expect(passage).not.toHaveAttribute('open');
    fireEvent.click(passage.querySelector('summary')!);
    expect(within(passage).getByText('Second inspection.')).toBeVisible();
    expect(within(quotedClaim).getByText('Pass')).toBeVisible();
    expect(within(quotedClaim).getByText('Score 1.00')).toBeVisible();
    expect(quotedClaim).toHaveTextContent('The log confirms the replacement held.');
    const legacy = screen.getByText('Historical factual grade').closest('details')!;
    fireEvent.click(within(legacy).getByText('Historical factual grade'));
    await within(legacy).findByText('This run recorded a single grade for the section.');
    expect(within(legacy).getByText('Original section assessment').closest('details')).not.toHaveAttribute('open');
    expect(within(legacy).queryByText('Judge assessment')).toBeNull();
    const conditions = screen.getByText('Test conditions').closest('details')!;
    fireEvent.click(within(conditions).getByText('Test conditions'));
    await within(conditions).findByText('Quoted in this assessment');
    expect(within(conditions).getByText('Claim 2')).toBeVisible();
    expect(within(conditions).getByText('Other section claims (1)').closest('details')).not.toHaveAttribute('open');
  });

  test('shows a live "k of N cases" indicator while a run is in progress', async () => {
    mockGet(runningDetail);
    render(<ExperimentDetail experimentId="e1" onBack={noop} onEdit={noop} />);

    // Body progress bar: count, label and percentage (3/5 = 60%).
    await waitFor(() =>
      expect(screen.getByText(/3 of 5 cases processed/i)).toBeInTheDocument(),
    );
    expect(screen.getByText('60%')).toBeInTheDocument();
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '3');
    expect(bar).toHaveAttribute('aria-valuemax', '5');
  });

  test('does not show the progress indicator once the run is completed', async () => {
    mockGet(completedDetail);
    render(<ExperimentDetail experimentId="e1" onBack={noop} onEdit={noop} />);

    // Completed runs show real stats, not progress.
    await waitFor(() => expect(screen.getByText('COVID eval')).toBeInTheDocument());
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText(/cases processed/i)).not.toBeInTheDocument();
  });
});
