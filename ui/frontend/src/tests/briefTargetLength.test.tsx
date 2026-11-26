import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axios from 'axios';
import { BriefTab } from '../components/brief/BriefTab';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: false,
}));
jest.mock('../components/brief/briefCitationsApi', () =>
  require('./helpers/fakeBriefCitations').fakeCitationsApi(),
);
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: null }),
}));
// Activity logging posts each auto-save; resolve it so the save path is exercised.
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: jest.fn().mockResolvedValue({ data: [] }),
    post: jest.fn().mockResolvedValue({ data: {} }),
    put: jest.fn().mockResolvedValue({ data: {} }),
    delete: jest.fn().mockResolvedValue({ data: {} }),
  },
}));

// Keep the real helpers (isLikelyNonAnswer etc.); stub only the network calls.
const mockRequestOutline = jest.fn();
const mockResearchSection = jest.fn();
const mockRunDeepResearch = jest.fn();
const mockRequestRevise = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/briefStream'),
  requestBriefOutline: (...args: unknown[]) => mockRequestOutline(...args),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
  runDeepResearch: (...args: unknown[]) => mockRunDeepResearch(...args),
  requestBriefRevise: (...args: unknown[]) => mockRequestRevise(...args),
}));

const SHORT_OPTION = '150'; // the "Short" preset
const START = 'Start deep research →';
const MANUAL = 'Write my own headings';
const sentence = 'The programme raised enrolment in the districts it covered [1]. ';
// Nine prose words per sentence (the [1] marker is not a word).
const longText = sentence.repeat(30); // 270 words, well over the Short target
const condensedText = sentence.repeat(14); // 126 words, within tolerance of 150
const source = { chunkId: 'c1', docId: 'd1', title: 'Doc', text: 'x', score: 0.5, page: 1, index: 1 };

// A researched section: the mock resolves with a source and the given content.
const answerWith = (content: string) => async ({ handlers }: any) => {
  handlers.onSources([source]);
  handlers.onDone({ content, sources: [source] });
};

describe('Brief section length target', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    // CRA's jest config resets mock implementations before each test, so the
    // activity-log post must be re-armed here or its .catch() has no promise.
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    mockRunDeepResearch.mockImplementation(async ({ handlers }: any) => {
      handlers.onSources([]);
      handlers.onDone({ content: '', sources: [] });
    });
  });

  const startManualBriefWithShortTarget = () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.change(screen.getByLabelText('Section length'), { target: { value: SHORT_OPTION } });
    fireEvent.click(screen.getByText(MANUAL));
  };

  // "Start deep research" opens the Regenerate-all modal, whose Length control
  // is pre-filled with the brief's target; submitting it starts the run.
  const runDeepResearch = () => {
    fireEvent.click(screen.getByText(START));
    expect(screen.getByLabelText('Section length')).toHaveValue(SHORT_OPTION);
    fireEvent.click(screen.getByRole('button', { name: /Regenerate all sections/ }));
  };

  test('the seed screen target is sent with every section research request', async () => {
    mockResearchSection.mockImplementation(answerWith(condensedText));
    startManualBriefWithShortTarget();
    runDeepResearch();
    await waitFor(() => expect(screen.getAllByText('126 words').length).toBeGreaterThan(0));
    expect(mockResearchSection).toHaveBeenCalled();
    mockResearchSection.mock.calls.forEach(([args]) => expect(args.targetWords).toBe(150));
    // 126 words is within the tolerance band of 150: no condense pass.
    expect(mockRequestRevise).not.toHaveBeenCalled();
  });

  test('a section that overshoots the target is condensed with an AI edit that keeps citations', async () => {
    mockResearchSection.mockImplementation(answerWith(longText));
    mockRequestRevise.mockResolvedValue(condensedText);
    startManualBriefWithShortTarget();
    runDeepResearch();

    await waitFor(() => expect(mockRequestRevise).toHaveBeenCalled());
    const [reviseArgs] = mockRequestRevise.mock.calls[0];
    expect(reviseArgs.content).toBe(longText);
    expect(reviseArgs.instruction).toContain('approximately 150 words');
    expect(reviseArgs.instruction).toContain('currently about 270 words');
    expect(reviseArgs.instruction).toContain('[n] citation marker');

    // The condensed text replaces the long draft, and the count reflects it.
    await waitFor(() => expect(screen.getAllByText('126 words').length).toBeGreaterThan(0));
    expect(screen.queryByText('270 words')).toBeNull();
  });

  test('with no target nothing is condensed', async () => {
    mockResearchSection.mockImplementation(answerWith(longText));
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(MANUAL));
    fireEvent.click(screen.getByText(START));
    expect(screen.getByLabelText('Section length')).toHaveValue('none');
    fireEvent.click(screen.getByRole('button', { name: /Regenerate all sections/ }));
    await waitFor(() => expect(screen.getAllByText('270 words').length).toBeGreaterThan(0));
    mockResearchSection.mock.calls.forEach(([args]) => expect(args.targetWords).toBeNull());
    expect(mockRequestRevise).not.toHaveBeenCalled();
  });

  test('the target is saved with the brief', async () => {
    mockResearchSection.mockImplementation(answerWith(condensedText));
    startManualBriefWithShortTarget();
    runDeepResearch();
    await waitFor(() => expect(screen.getAllByText('126 words').length).toBeGreaterThan(0));
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem('evidencelab_brief_history_v1') || '[]');
      expect(saved[0]?.targetWords).toBe(150);
    });
  });

  test('a failed regeneration keeps the previous section visible during and after the run', async () => {
    mockResearchSection.mockImplementation(answerWith(condensedText));
    startManualBriefWithShortTarget();
    runDeepResearch();
    const [regenerate] = await screen.findAllByRole('button', { name: 'AI Regenerate' });
    const section = regenerate.closest('section');
    if (!section) throw new Error('The regenerate button must belong to a section');
    const originalText = section.querySelector('.brief-doc-content')?.textContent;
    expect(originalText).toContain('The programme raised enrolment');

    let fail = () => { throw new Error('The regression run did not start'); };
    mockResearchSection.mockImplementationOnce(({ handlers }) => new Promise<void>((resolve) => {
      handlers.onToken('Unsaved replacement');
      fail = () => {
        handlers.onError('The research could not be completed.');
        resolve();
      };
    }));
    fireEvent.click(regenerate);
    fireEvent.click(within(section).getByRole('button', { name: 'Re-research section' }));
    await waitFor(() => expect(section.querySelector('.brief-researching')).toBeInTheDocument());
    expect(section.querySelector('.brief-doc-content')?.textContent).toEqual(originalText);
    expect(within(section).queryByText('Unsaved replacement')).toBeNull();

    await act(async () => fail());
    expect(await within(section).findByText('The research could not be completed.')).toBeInTheDocument();
    expect(within(section).getByText('You’re viewing the previous draft.')).toBeInTheDocument();
    expect(section.querySelector('.brief-doc-content')?.textContent).toEqual(originalText);
    expect(section.querySelector('.brief-researching')).toBeNull();
    fireEvent.click(within(section).getByRole('button', { name: 'Research settings' }));
    expect(within(section).getByRole('button', { name: 'Re-research section' })).toBeInTheDocument();
    fireEvent.click(within(section).getByRole('button', { name: 'Cancel' }));
    mockResearchSection.mockClear();
    fireEvent.click(within(section).getByRole('button', { name: 'Retry regeneration' }));
    expect(mockResearchSection).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(within(section).queryByText('AI regeneration failed')).toBeNull());
  });

  test('regenerate all counts only newly saved sections and retains drafts for interrupted runs', async () => {
    mockResearchSection.mockImplementation(answerWith(condensedText));
    startManualBriefWithShortTarget();
    runDeepResearch();
    const complete = await screen.findByText(/^Updated \d+ of \d+ sections\.$/);
    const total = Number(complete.textContent?.match(/of (\d+)/)?.[1]);
    expect(total).toBeGreaterThan(1);
    expect(complete).toHaveTextContent(`Updated ${total} of ${total} sections.`);

    let finish: () => void = () => { throw new Error('The regression run did not start'); };
    mockResearchSection.mockImplementation(async () => {});
    mockResearchSection.mockImplementationOnce(({ handlers }) => new Promise<void>((resolve) => {
      finish = () => {
        handlers.onDone({
          content: 'The evaluation measured attendance in participating schools [1].',
          sources: [source],
        });
        resolve();
      };
    }));
    fireEvent.click(screen.getByRole('button', { name: 'AI Regenerate All' }));
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate all sections' }));
    expect(await screen.findAllByText(`0 of ${total} updated`)).not.toHaveLength(0);
    await act(async () => finish());

    expect(await screen.findByText(`Updated 1 of ${total} sections.`)).toBeInTheDocument();
    expect(screen.getByText(/The evaluation measured attendance/)).toBeInTheDocument();
    expect(screen.getAllByText(/The programme raised enrolment/).length).toBeGreaterThan(0);
    const failures = total - 1;
    expect(screen.getAllByLabelText('AI research failed')).toHaveLength(failures);
    expect(screen.getAllByText('Research ended before a draft was ready.')).toHaveLength(failures);
    const original = mockResearchSection.mock.calls.slice(-total)[0][0].heading;
    mockResearchSection.mockClear();
    mockResearchSection.mockImplementation(answerWith(condensedText));
    fireEvent.click(screen.getByRole('button', { name: `Retry failed sections (${failures})` }));

    expect(await screen.findByText(`Updated ${failures} of ${failures} sections.`)).toBeInTheDocument();
    expect(mockResearchSection).toHaveBeenCalledTimes(failures);
    expect(mockResearchSection.mock.calls.map(([args]) => args.heading)).not.toContain(original);
    expect(screen.queryByLabelText('AI research failed')).not.toBeInTheDocument();
    expect(screen.getByText(/The evaluation measured attendance/)).toBeInTheDocument();
  });
});
