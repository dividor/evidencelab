import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// USER_MODULE on + an authenticated user => Brief Central, server briefs.
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));
jest.mock('../components/brief/briefCitationsApi', () =>
  require('./helpers/fakeBriefCitations').fakeCitationsApi(),
);
jest.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'u1' } }) }));

const mockGet = jest.fn();
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: jest.fn().mockResolvedValue({ data: {} }),
    put: jest.fn().mockResolvedValue({ data: {} }),
    delete: jest.fn().mockResolvedValue({ data: {} }),
    isAxiosError: () => false,
  },
}));
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  requestBriefOutline: jest.fn(),
  researchBriefSection: jest.fn(),
  runDeepResearch: jest.fn(),
}));

import { BriefTab } from '../components/brief/BriefTab';
import type { BriefFactCheckRead } from '../types/testing';

const TITLE = 'School feeding';
const PASSAGE = 'School meals raised attendance.';
const WHY = 'The excerpt reports no change in attendance.';
const FACT_CHECKER = 'Fact Checker';
const BRIEF_URL = '/api/briefs/b1';
const FACT_CHECK_URL = '/api/briefs/b1/fact-check';

const source = { index: 1, chunkId: 'c1', docId: 'd1', title: 'Doc One', text: 'passage', score: 0, page: 3 };

const listItem = {
  id: 'b1', title: TITLE, query: 'nutrition', data_source: 'wfp', voice_profile_id: null,
  section_count: 1, source_count: 1, owner_name: null, share_count: 0,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
};

const remoteBrief = {
  id: 'b1', user_id: 'u1', title: TITLE, query: 'nutrition', data_source: 'wfp', voice_profile_id: null,
  owner_name: null, can_edit: true, shared_with: [],
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
  content: {
    id: 'b1', title: TITLE, query: 'nutrition', date: 1, sectionCount: 1, sourceCount: 1,
    citationsVersion: 2, referenceGrouping: 'passage', references: [], referenceGroups: [],
    sections: [
      {
        id: 's1', title: 'Findings', level: 1, status: 'done', runs: [], currentRunId: null,
        renumbered: { content: 'School meals raised attendance [1]. Costs rose [1].', sources: [source], unresolved: [] },
      },
    ],
  },
};

const withCheck: BriefFactCheckRead = {
  check: {
    id: 'chk1', brief_id: 'b1', brief_title: TITLE, status: 'completed',
    created_at: '2026-11-02T00:00:00Z', judge_model: 'gpt-4.1-mini',
  },
  highlight_verdicts: ['unsupported'],
  marks: [
    {
      passage_id: 1, section_id: 's1', section_title: 'Findings', passage: PASSAGE,
      verdict: 'unsupported', verdict_label: 'Unsupported', explanation: WHY,
      problems: ['Contradicted by the source'], confidence: 0.9, citations: '1', quote_not_in_source: false,
    },
  ],
};

const noCheck: BriefFactCheckRead = { check: null, highlight_verdicts: ['unsupported'], marks: [] };

const answer = (factCheck: BriefFactCheckRead) => (url: string) => {
  if (url === '/api/briefs/') return Promise.resolve({ data: [listItem] });
  if (url === BRIEF_URL) return Promise.resolve({ data: remoteBrief });
  if (url === FACT_CHECK_URL) return Promise.resolve({ data: factCheck });
  return Promise.resolve({ data: [] });
};

const openBrief = async () => {
  render(<BriefTab dataSource="wfp" />);
  fireEvent.click(await screen.findByTitle('Open this brief'));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith(BRIEF_URL));
  await screen.findByText('Export to Word');
};

describe('Fact Checker on an open brief', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    window.history.replaceState(null, '', '/brief');
  });

  test('a completed check for the current brief shows the button; pressing it highlights the flagged passage with the judge\'s explanation on hover', async () => {
    mockGet.mockImplementation(answer(withCheck));
    await openBrief();
    const button = await screen.findByRole('button', { name: FACT_CHECKER });
    expect(mockGet).toHaveBeenCalledWith(FACT_CHECK_URL);
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(document.querySelector('.brief-fact-mark')).toBeNull();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'true');
    const mark = await waitFor(() => {
      const el = document.querySelector('.brief-fact-mark-unsupported');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // The judged sentence is marked up to its full stop, as one span either
    // side of the citation badge; the rest of the section is untouched.
    const markText = () =>
      Array.from(document.querySelectorAll('[data-fact-id="1"]')).map((m) => m.textContent).join('');
    expect(markText()).toBe('School meals raised attendance .');
    expect(document.querySelectorAll('.brief-fact-mark:not([data-fact-id="1"])').length).toBe(0);

    fireEvent.mouseOver(mark);
    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveTextContent('Unsupported');
    expect(tooltip).toHaveTextContent('90% confidence');
    expect(tooltip).toHaveTextContent('Contradicted by the source');
    expect(tooltip).toHaveTextContent(WHY);
    expect(tooltip).toHaveTextContent('Judged against the sources cited as [1]');

    // Source enrichment re-renders the section meanwhile and the painter puts
    // the mark back, so read the prose container afresh.
    fireEvent.mouseLeave(document.querySelector('.brief-doc-content') as HTMLElement);
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());

    // Pressing again hides the highlights.
    fireEvent.click(button);
    await waitFor(() => expect(document.querySelector('.brief-fact-mark')).toBeNull());
  });

  test('without a check that matches the brief as it is now, there is no button', async () => {
    mockGet.mockImplementation(answer(noCheck));
    await openBrief();
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(FACT_CHECK_URL));
    expect(screen.queryByRole('button', { name: FACT_CHECKER })).toBeNull();
  });
});
