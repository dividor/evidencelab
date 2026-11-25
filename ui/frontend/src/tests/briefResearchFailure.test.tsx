import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import { BriefTab } from '../components/brief/BriefTab';
import { failedResearchState } from '../components/brief/useBrief';
import type { BriefSection } from '../components/brief/briefTypes';

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
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: jest.fn().mockResolvedValue({ data: [] }),
    post: jest.fn().mockResolvedValue({ data: {} }),
    put: jest.fn().mockResolvedValue({ data: {} }),
    delete: jest.fn().mockResolvedValue({ data: {} }),
  },
}));

const mockResearchSection = jest.fn();
const mockRunDeepResearch = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  ...jest.requireActual('../utils/briefStream'),
  requestBriefOutline: jest.fn(),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
  runDeepResearch: (...args: unknown[]) => mockRunDeepResearch(...args),
  requestBriefRevise: jest.fn(),
}));

// What the API sends when a search inside the research run fails.
const SEARCH_FAILED =
  'Search failed, so this could not be researched. Try again, or ask your administrator to check the search service.';
const WRITTEN = 'The programme raised enrolment in the districts it covered [1]. ';
const source = { chunkId: 'c1', docId: 'd1', title: 'Doc', text: 'x', score: 0.5, page: 1, index: 1 };

const answers = async ({ handlers }: any) => {
  handlers.onSources([source]);
  handlers.onDone({ content: WRITTEN.repeat(12), sources: [source] });
};
const searchFails = async ({ handlers }: any) => {
  handlers.onError(SEARCH_FAILED);
};

const writtenSections = () => screen.queryAllByText(/raised enrolment in the districts/);

// A manual brief whose three starter sections are researched by "Regenerate all".
const researchAllSections = async () => {
  render(<BriefTab dataSource="wfp" />);
  fireEvent.click(screen.getByText('Write my own headings'));
  fireEvent.click(screen.getByText('Start deep research →'));
  fireEvent.click(screen.getByRole('button', { name: /Regenerate all sections/ }));
};

describe('Brief section research that fails', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    mockRunDeepResearch.mockImplementation(async ({ handlers }: any) => {
      handlers.onSources([]);
      handlers.onDone({ content: '', sources: [] });
    });
  });

  test('a failed Regenerate shows the error and puts the section text back', async () => {
    mockResearchSection.mockImplementation(answers);
    await researchAllSections();
    await waitFor(() => expect(writtenSections()).toHaveLength(3));

    mockResearchSection.mockImplementation(searchFails);
    fireEvent.click(screen.getAllByRole('button', { name: /AI Regenerate$/ })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Re-research section' }));

    expect(await screen.findByText(SEARCH_FAILED)).toBeInTheDocument();
    expect(mockResearchSection).toHaveBeenCalledTimes(4);
    expect(writtenSections()).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Research section' })).toBeNull();
  });

  test('a failed first research shows the error and leaves the section to research', async () => {
    mockResearchSection.mockImplementation(searchFails);
    await researchAllSections();

    expect(await screen.findByText(SEARCH_FAILED)).toBeInTheDocument();
    await waitFor(() => expect(mockResearchSection).toHaveBeenCalledTimes(3));
    expect(writtenSections()).toHaveLength(0);
  });
});

describe('failedResearchState', () => {
  const section = (over: Partial<BriefSection>): BriefSection =>
    ({ id: 's1', title: 'S', level: 1, status: 'pending', content: '', sources: [], ...over }) as BriefSection;

  test('an Update or Edit keeps the draft it never cleared', () => {
    expect(failedResearchState(true, section({ status: 'done', content: 'Old' }))).toEqual({
      status: 'done',
      progress: 100,
      revising: undefined,
    });
  });

  test('a Generate over written text gets that text and its sources back', () => {
    const before = section({ status: 'done', content: 'Old [1].', sources: [source] as any });
    expect(failedResearchState(false, before)).toEqual({
      status: 'done',
      progress: 100,
      content: 'Old [1].',
      sources: [source],
    });
  });

  test('a first research goes back to pending', () => {
    expect(failedResearchState(false, section({}))).toEqual({ status: 'pending', progress: 0 });
  });
});
