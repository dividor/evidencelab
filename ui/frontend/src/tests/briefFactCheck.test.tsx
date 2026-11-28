import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { BriefTab } from '../components/brief/BriefTab';
import type { BriefFactCheckEvidenceRead, BriefFactCheckRead } from '../types/testing';

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

const CREATED_AT = '2026-11-01T00:00:00Z';
const DOC_ONE_LABEL = '[1] Doc One · p. 3';
const OPEN_BRIEF = 'Open this brief';
const EXPORT_WORD = 'Export to Word';
const FACT_MARK_SELECTOR = '.brief-fact-mark';
const MISSING_PERIOD = 'The comparison period is missing.';
const FACT_LEGEND = 'Fact Checker legend';

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

const TITLE = 'School feeding';
const PASSAGE = 'School meals raised attendance.';
const WHY = 'The excerpt reports no change in attendance.';
const FACT_CHECKER = 'Fact Checker';
const BRIEF_URL = '/api/briefs/b1';
const FACT_CHECK_URL = '/api/briefs/b1/fact-check';
const EVIDENCE_URL = '/api/briefs/b1/fact-check/chk1/passages/1';
const QUOTED = 'attendance did not change';

const source = { index: 1, chunkId: 'c1', docId: 'd1', title: 'Doc One', text: 'passage', score: 0, page: 3 };

const listItem = {
  id: 'b1', title: TITLE, query: 'nutrition', data_source: 'wfp', voice_profile_id: null,
  section_count: 1, source_count: 1, owner_name: null, share_count: 0,
  created_at: CREATED_AT, updated_at: CREATED_AT,
};

const remoteBrief = {
  id: 'b1', user_id: 'u1', title: TITLE, query: 'nutrition', data_source: 'wfp', voice_profile_id: null,
  owner_name: null, can_edit: true, shared_with: [],
  created_at: CREATED_AT, updated_at: CREATED_AT,
  content: {
    id: 'b1', title: TITLE, query: 'nutrition', date: 1, sectionCount: 1, sourceCount: 1,
    citationsVersion: 2, referenceGrouping: 'passage', references: [], referenceGroups: [],
    sections: [
      {
        id: 's1', title: 'Findings', level: 1, status: 'done', runs: [], currentRunId: null,
        renumbered: { content: 'School meals raised attendance [1]. Costs rose [1].', sources: [source], unresolved: [] },
      },
      {
        id: 's2', title: 'Costs', level: 1, status: 'done', runs: [], currentRunId: null,
        renumbered: { content: 'Costs fell sharply [1].', sources: [source], unresolved: [] },
      },
    ],
  },
};

const NOTE = 'Checked at version 1; the brief is now at version 2. 1 section changed since and is not highlighted: “Costs”.';
const SECTION_NOTE = 'Changed since the citation check (version 1); not covered by the Fact Checker.';

const withCheck: BriefFactCheckRead = {
  check: {
    id: 'chk1', brief_id: 'b1', brief_title: TITLE, status: 'completed',
    created_at: '2026-11-02T00:00:00Z', judge_model: 'gpt-4.1-mini',
    brief_version_number: 1, brief_changed: true,
  },
  brief_version: 1,
  current_version: 2,
  note: NOTE,
  changed_sections: [{ id: 's2', title: 'Costs', note: SECTION_NOTE }],
  legend: [
    { verdict: 'supported', label: 'Supported', count: 1 },
    { verdict: 'partially_supported', label: 'Partially supported', count: 0 },
    { verdict: 'unsupported', label: 'Unsupported', count: 1 },
    { verdict: 'cannot_assess', label: 'Cannot assess', count: 0 },
  ],
  marks: [
    {
      passage_id: 1, section_id: 's1', section_title: 'Findings', passage: PASSAGE,
      verdict: 'unsupported', verdict_label: 'Unsupported', explanation: WHY,
      problems: ['Contradicted by the source'], confidence: 0.9, citations: '1', quote_not_in_source: false,
    },
    {
      passage_id: 2, section_id: 's1', section_title: 'Findings', passage: 'Costs rose.',
      verdict: 'supported', verdict_label: 'Supported', explanation: 'Stated in the excerpt.',
      problems: [], confidence: 0.95, citations: '1', quote_not_in_source: false,
    },
  ],
};

const evidence: BriefFactCheckEvidenceRead = {
  passage_id: 1,
  verdict: 'unsupported',
  verdict_label: 'Unsupported',
  evidence: [
    {
      citation: 1, label: DOC_ONE_LABEL, title: 'Doc One', page: 3, section: 'Findings > Schools',
      doc_id: 'd1', chunk_id: 'c1', pdf_url: null, quoted: true,
      segments: [
        { text: 'In the sample schools ', highlighted: false },
        { text: QUOTED, highlighted: true },
        { text: ' over the two years.', highlighted: false },
      ],
    },
  ],
};

const noCheck: BriefFactCheckRead = { check: null, legend: [], marks: [] };

const answer = (factCheck: BriefFactCheckRead) => (url: string) => {
  if (url === '/api/briefs/') return Promise.resolve({ data: [listItem] });
  if (url === BRIEF_URL) return Promise.resolve({ data: remoteBrief });
  if (url === FACT_CHECK_URL) return Promise.resolve({ data: factCheck });
  if (url === EVIDENCE_URL) return Promise.resolve({ data: evidence });
  return Promise.resolve({ data: [] });
};

const openBrief = async () => {
  render(<BriefTab dataSource="wfp" />);
  fireEvent.click(await screen.findByTitle(OPEN_BRIEF));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith(BRIEF_URL));
  await screen.findByText(EXPORT_WORD);
};

describe('Fact Checker on an open brief', () => {
  beforeAll(() => {
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true; } },
      close: { configurable: true, value(this: HTMLDialogElement) { this.open = false; } },
    });
  });
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    window.history.replaceState(null, '', '/brief');
  });

  test('comments start hidden and remember an explicit choice to show them', async () => {
    mockGet.mockImplementation(answer(noCheck));
    await openBrief();
    const toggle = screen.getByRole('checkbox', { name: 'Show comments' });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(localStorage.getItem('evidencelab_brief_show_comments')).toBe('true');
  });

  test('the source title opens the source panel and closes the claim dialog', async () => {
    mockGet.mockImplementation(answer(withCheck));
    const onResultClick = jest.fn();
    render(<BriefTab dataSource="wfp" onResultClick={onResultClick} />);
    fireEvent.click(await screen.findByTitle(OPEN_BRIEF));
    fireEvent.click(await screen.findByRole('button', { name: FACT_CHECKER }));
    fireEvent.click(await waitFor(() => {
      const mark = document.querySelector(FACT_MARK_SELECTOR);
      if (!mark) throw Error('Waiting for highlight');
      return mark;
    }));
    expect(screen.queryByRole('button', { name: 'See Text' })).toBeNull();
    fireEvent.click(await screen.findByRole('link', { name: DOC_ONE_LABEL }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onResultClick).toHaveBeenCalledWith(expect.objectContaining({ doc_id: 'd1', chunk_id: 'c1', page_num: 3 }));
  });

  test('opening a saved brief shows the loading animation until its sections arrive', async () => {
    let finish!: (value: { data: typeof remoteBrief }) => void;
    const pending = new Promise((resolve) => { finish = resolve; });
    mockGet.mockImplementation((url) => url === BRIEF_URL ? pending : answer(noCheck)(url));
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(await screen.findByTitle(OPEN_BRIEF));
    expect(screen.getByRole('status', { name: 'Loading' })).toHaveClass('search-loading-wandering');
    expect(screen.queryByTitle(OPEN_BRIEF)).toBeNull();
    await act(async () => finish({ data: remoteBrief }));
    expect(await screen.findByText(EXPORT_WORD)).toBeVisible();
    expect(screen.queryByRole('status', { name: 'Loading' })).toBeNull();
  });

  test('an open Brief preserves the Admin URL and restores its link when the user returns', async () => {
    mockGet.mockImplementation(answer(noCheck));
    const { rerender } = render(<BriefTab dataSource="wfp" />);
    fireEvent.click(await screen.findByTitle(OPEN_BRIEF));
    await screen.findByText(EXPORT_WORD);
    const admin = '/admin?admin_page=testing&admin_testing=experiments';
    window.history.pushState(null, '', admin);
    rerender(<BriefTab dataSource="wfp" isActive={false} />);
    expect(window.location.pathname + window.location.search).toBe(admin);

    window.history.pushState(null, '', '/brief?tab=brief');
    rerender(<BriefTab dataSource="wfp" isActive />);
    expect(window.location.pathname + window.location.search).toBe('/brief/b1?tab=brief');
  });

  test('a partially supported sentence stays amber and opens the gap and quoted evidence', async () => {
    const partial = { ...withCheck.marks[0], verdict: 'partially_supported' as const,
      claim_text: 'School meals raised attendance [1].',
      grade: { claim: 1, score: 0.5, passed: false, verdict: 'partially_supported' as const, reason: WHY, unmet: [MISSING_PERIOD] },
      verdict_label: 'Partially supported', problems: [MISSING_PERIOD] };
    mockGet.mockImplementation(answer({ ...withCheck, marks: [partial] }));
    await openBrief();
    fireEvent.click(await screen.findByRole('button', { name: FACT_CHECKER }));
    const mark = await waitFor(() => {
      const found = document.querySelector<HTMLElement>('.brief-fact-mark.brief-fact-mark-partially_supported');
      if (!found) throw Error('Waiting for the sentence highlight');
      return found;
    });
    fireEvent.mouseOver(mark);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Claim 1' }));
    const card = await screen.findByRole('dialog', { name: 'Claim 1' });
    expect(card).toHaveTextContent('Score 0.50');
    expect(card).not.toHaveTextContent(/Fail|Required/);
    expect(card).toHaveTextContent('School meals raised attendance [1].');
    expect(card).toHaveTextContent('Judge assessment');
    expect(card).toHaveTextContent('What the evidence does not establish');
    expect(card).toHaveTextContent(MISSING_PERIOD);
    expect(await screen.findByRole('link', { name: DOC_ONE_LABEL })).toHaveAttribute('href', '#');
    expect(card.querySelector('blockquote q')).toHaveTextContent(partial.claim_text);
    expect(card.querySelector('.brief-fact-quote')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'See more' })).toBeNull();
    expect(card).toBeVisible();
    fireEvent.click(card, { clientX: -2, clientY: -2 });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('a completed check for the current brief shows the button; pressing it highlights every judged passage in its verdict\'s colour, with the verdict, reason and evidence on click', async () => {
    mockGet.mockImplementation(answer(withCheck));
    await openBrief();
    const button = await screen.findByRole('button', { name: FACT_CHECKER });
    expect(mockGet).toHaveBeenCalledWith(FACT_CHECK_URL);
    expect(button).toHaveAttribute('aria-pressed', 'false');
    // The tooltip says which version was checked and how the brief moved on.
    expect(button).toHaveAttribute('title', expect.stringContaining(NOTE));
    expect(document.querySelector(FACT_MARK_SELECTOR)).toBeNull();
    expect(screen.queryByText(SECTION_NOTE)).toBeNull();
    expect(screen.queryByRole('list', { name: FACT_LEGEND })).toBeNull();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'true');
    // The legend explains the colours, with the API's counts.
    const legend = screen.getByRole('list', { name: FACT_LEGEND });
    expect(legend).toHaveTextContent('Supported 1');
    expect(legend).toHaveTextContent('Unsupported 1');
    expect(legend).toHaveTextContent('Cannot assess 0');
    // The section changed since the check carries the note instead of marks.
    expect(await screen.findByText(SECTION_NOTE)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('.brief-fact-mark.brief-fact-mark-unsupported')).not.toBeNull());
    // Both judged sentences are marked, each in its verdict's colour; the
    // first up to its full stop, as one span either side of the citation
    // badge.
    const markText = (id: string) =>
      Array.from(document.querySelectorAll(`[data-fact-id="${id}"]`)).map((m) => m.textContent).join('');
    expect(markText('1')).toBe('School meals raised attendance .');
    expect(markText('2')).toBe('Costs rose .');
    expect(document.querySelector('[data-fact-id="2"]')).toHaveClass('brief-fact-mark-supported');
    expect(document.querySelectorAll('.brief-fact-mark:not([data-fact-id="1"]):not([data-fact-id="2"])').length).toBe(0);

    fireEvent.click(document.querySelector('.brief-fact-mark.brief-fact-mark-unsupported') as HTMLElement);
    const card = await screen.findByRole('dialog', { name: 'Citation check verdict' });
    expect(card).toHaveTextContent('Unsupported');
    expect(card).toHaveTextContent('90% confidence');
    expect(card).toHaveTextContent('Judged against [1]');
    expect(card).toHaveTextContent(WHY);
    // The evidence is fetched for this passage once its card opens: the cited
    // excerpt, with what the judge quoted highlighted.
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(EVIDENCE_URL));
    await waitFor(() => expect(card).toHaveTextContent(DOC_ONE_LABEL));
    expect(card).toHaveTextContent('Sources');
    expect(card).toHaveTextContent('In the sample schools attendance did not change over the two years.');
    expect(card.querySelector('.brief-fact-quote')).toHaveTextContent(QUOTED);

    fireEvent.mouseLeave(card);
    expect(card).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Close claim' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    // Pressing again hides the highlights, the legend and the note.
    fireEvent.click(button);
    await waitFor(() => expect(document.querySelector(FACT_MARK_SELECTOR)).toBeNull());
    expect(screen.queryByText(SECTION_NOTE)).toBeNull();
    expect(screen.queryByRole('list', { name: FACT_LEGEND })).toBeNull();
  });

  test('without a check that matches the brief as it is now, there is no button', async () => {
    mockGet.mockImplementation(answer(noCheck));
    await openBrief();
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(FACT_CHECK_URL));
    expect(screen.queryByRole('button', { name: FACT_CHECKER })).toBeNull();
  });
});
