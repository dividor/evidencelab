import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axios from 'axios';
import BriefCheckDetail from '../components/admin/testing/BriefCheckDetail';
import BriefCheckList from '../components/admin/testing/BriefCheckList';
import BriefTestingManager from '../components/admin/BriefTestingManager';
import { EMPTY_FILTERS, filterPassages } from '../components/admin/testing/citationCheckFormat';
import type { BriefCitationCheckPassage } from '../types/testing';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const TS = '2026-09-24T10:00:00Z';
const KENYA = 'Kenya evaluation';
const BRIEF_TITLE = 'School feeding';
const GIRLS = 'Girls benefited most.';

const check = {
  id: 'chk1',
  brief_id: 'b1',
  brief_title: BRIEF_TITLE,
  status: 'completed',
  judge_model: 'gpt-4.1-mini',
  model_combo: 'Azure Foundry',
  created_at: TS,
  summary_stats: {
    total: 3,
    verdicts: { supported: 1, partially_supported: 1, unsupported: 1, cannot_assess: 0 },
    flagged: 2,
    flagged_share: 0.67,
    quote_not_in_source: 1,
    by_section: [
      { brief_section: 'Dropout', supported: 1, partially_supported: 1, unsupported: 1, cannot_assess: 0, total: 3, flagged_share: 0.67 },
    ],
    duration_ms: 1500,
    total_tokens: 1200,
    cost_usd: 0.002,
  },
};

const passage = (over: Partial<BriefCitationCheckPassage>): BriefCitationCheckPassage => ({
  id: 'p', passage_id: 1, brief_section: 'Dropout', passage: 'Dropout fell.', citations: '1',
  documents: `[1] ${KENYA}`, sources: [{ index: 1, title: KENYA, page: 4, pdf_url: 'https://x/y.pdf', excerpt: 'Dropout fell from 12 to 7 percent.' }],
  dangling_citations: '', verdict: 'supported', flagged: false, confidence: 0.9, problems: [],
  explanation: 'Matches the excerpt.', supporting_quotes: [{ citation: 1, quote: 'Dropout fell from 12 to 7 percent', status: 'verbatim' }],
  quotes_verified: '1/1', quote_not_in_source: false, ...over,
});

const passages = [
  passage({ id: 'p1', passage_id: 1 }),
  passage({ id: 'p2', passage_id: 2, passage: GIRLS, verdict: 'partially_supported', flagged: true, problems: ['Excerpt does not mention girls.'], quote_not_in_source: true, supporting_quotes: [{ citation: 1, quote: 'girls benefited', status: 'missing' }], quotes_verified: '0/1' }),
  passage({ id: 'p3', passage_id: 3, brief_section: 'Costs', passage: 'Costs halved.', verdict: 'unsupported', flagged: true, confidence: 0.4 }),
];

const CASH = 'Cash transfers';
const NUTRITION = 'Nutrition outcomes';
const briefs = [
  { id: 'b1', title: BRIEF_TITLE, data_source: 'wfp', updated_at: TS, owner_name: 'Jan', access: 'own', researched_sections: 2, cited_passages: 3, last_check: check },
  { id: 'b2', title: CASH, data_source: 'wfp', updated_at: TS, owner_name: 'Ana', access: 'shared', researched_sections: 1, cited_passages: 0, last_check: null },
  { id: 'b3', title: NUTRITION, data_source: 'wfp', updated_at: TS, owner_name: 'Bo', access: 'other', researched_sections: 1, cited_passages: 2, last_check: null },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/testing/briefs')) return Promise.resolve({ data: briefs });
    if (url.includes('/config/model-combos')) return Promise.resolve({ data: { 'Azure Foundry': {}, 'Google Vertex': {} } });
    if (url.includes('/testing/brief-checks/chk1')) return Promise.resolve({ data: { ...check, passages } });
    return Promise.resolve({ data: [] });
  });
});

describe('filterPassages', () => {
  test('combines verdict, flagged, quote and section filters', () => {
    expect(filterPassages(passages, EMPTY_FILTERS)).toHaveLength(3);
    expect(filterPassages(passages, { ...EMPTY_FILTERS, flaggedOnly: true }).map((p) => p.passage_id)).toEqual([2, 3]);
    expect(filterPassages(passages, { ...EMPTY_FILTERS, quoteNotInSource: true }).map((p) => p.passage_id)).toEqual([2]);
    expect(filterPassages(passages, { ...EMPTY_FILTERS, verdicts: new Set(['unsupported']) }).map((p) => p.passage_id)).toEqual([3]);
    expect(filterPassages(passages, { ...EMPTY_FILTERS, section: 'Costs' }).map((p) => p.passage_id)).toEqual([3]);
    expect(filterPassages(passages, { ...EMPTY_FILTERS, search: 'GIRLS' }).map((p) => p.passage_id)).toEqual([2]);
  });
});

describe('BriefTestingManager', () => {
  test('lists briefs and opens a check without a combo picker', async () => {
    render(<BriefTestingManager dataSource="wfp" modelCombo="Google Vertex" onResultClick={jest.fn()} />);
    await waitFor(() => expect(screen.getByText(BRIEF_TITLE)).toBeInTheDocument());
    expect(screen.queryByLabelText('Judge model combo')).toBeNull();
    expect(screen.queryByText(/summarisation model/)).toBeNull();
    fireEvent.click(screen.getByText(BRIEF_TITLE));
    await waitFor(() => expect(screen.getByRole('button', { name: /Briefs/ })).toBeInTheDocument());
  });
});

describe('BriefCheckList', () => {
  test("lists own, shared and other users' briefs, scopes them, and starts a check with the inherited combo", async () => {
    mockedAxios.post.mockResolvedValue({ data: { ...check, id: 'chk2', status: 'pending' } });
    const onOpenCheck = jest.fn();
    render(<BriefCheckList modelCombo="Google Vertex" onOpenCheck={onOpenCheck} />);
    await waitFor(() => expect(screen.getByText(CASH)).toBeInTheDocument());
    expect(screen.getByText(NUTRITION)).toBeInTheDocument();
    expect(screen.getByText('2 of 3 flagged (67%)')).toBeInTheDocument();
    expect(screen.getAllByText('shared')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'Shared with me' }));
    expect(screen.queryByText(BRIEF_TITLE)).toBeNull();
    expect(screen.queryByText(NUTRITION)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Other users' }));
    expect(screen.getByText(NUTRITION)).toBeInTheDocument();
    expect(screen.queryByText(CASH)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Mine' }));
    expect(screen.getByText(BRIEF_TITLE)).toBeInTheDocument();
    expect(screen.queryByText(NUTRITION)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'All' }));

    const runButtons = screen.getAllByRole('button', { name: 'Run check' });
    expect(runButtons[1]).toBeDisabled(); // no cited passages
    fireEvent.click(runButtons[0]);
    await waitFor(() => expect(onOpenCheck).toHaveBeenCalledWith(expect.objectContaining({ id: 'chk2' })));
    expect(mockedAxios.post).toHaveBeenCalledWith('/api/testing/brief-checks', {
      brief_id: 'b1',
      model_combo: 'Google Vertex',
    });
  });
});

describe('BriefCheckDetail', () => {
  test('shows the summary, filters the table and expands a passage', async () => {
    const onResultClick = jest.fn();
    render(<BriefCheckDetail check={check as never} dataSource="wfp" onBack={jest.fn()} onResultClick={onResultClick} />);
    await waitFor(() => expect(screen.getByText('Showing 3 of 3 passages.', { exact: false })).toBeInTheDocument());
    expect(screen.queryByRole('columnheader', { name: 'Documents' })).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: '[1]' })[0]);
    expect(onResultClick).toHaveBeenCalledWith(
      expect.objectContaining({ doc_id: '', title: KENYA, page_num: 4, text: 'Dropout fell from 12 to 7 percent.', data_source: 'wfp' }),
    );
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(GIRLS)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Flagged only'));
    expect(screen.getByText('Showing 2 of 3 passages.', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText('Dropout fell.')).toBeNull();

    fireEvent.click(screen.getByLabelText('Quote not in source'));
    expect(screen.getByText('Showing 1 of 3 passages.', { exact: false })).toBeInTheDocument();

    fireEvent.click(screen.getByText(GIRLS));
    expect(screen.getByText('Excerpt does not mention girls.')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /copy, word for word/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Quotes verified' })).toHaveAttribute('title', expect.stringContaining('Found / given'));
    expect(screen.queryByRole('columnheader', { name: 'Flagged share' })).toBeNull();
    expect(screen.getByText('missing')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: `[1] ${KENYA}, p. 4` }));
    expect(onResultClick).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('Showing 3 of 3 passages.', { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download Excel' })).toBeEnabled();
  });

  test('a running check shows progress and disables export', async () => {
    mockedAxios.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes('brief-checks')
          ? { ...check, status: 'running', summary_stats: { progress: { completed: 1, total: 3 } }, passages: [passages[0]] }
          : [],
      }),
    );
    render(<BriefCheckDetail check={{ ...check, status: 'running' } as never} dataSource="wfp" onBack={jest.fn()} />);
    await waitFor(() => expect(screen.getByText('1 of 3 passages judged')).toBeInTheDocument());
    expect(within(screen.getByRole('status')).getByText('33%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download Excel' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
  });
});
