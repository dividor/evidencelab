import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

// USER_MODULE on + an authenticated user => the brief is "logged in".
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

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const mockRunDeepResearch = jest.fn();
const mockRequestOutline = jest.fn();
const mockResearchSection = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  requestBriefOutline: (...a: unknown[]) => mockRequestOutline(...a),
  researchBriefSection: (...a: unknown[]) => mockResearchSection(...a),
  runDeepResearch: (...a: unknown[]) => mockRunDeepResearch(...a),
}));

import { BriefTab } from '../components/brief/BriefTab';

describe('Brief uses the group search settings when logged in', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockedAxios.get.mockImplementation(async (url) => ({
      data: url.endsWith('/fact-check') ? { check: null, legend: [], marks: [] } : [],
    }));
    mockedAxios.post.mockResolvedValue({ data: {} });
    mockedAxios.put.mockResolvedValue({ data: {} });
    mockedAxios.delete.mockResolvedValue({ data: {} });
    mockRunDeepResearch.mockImplementation(async ({ handlers }: any) => {
      handlers.onSources([]);
      handlers.onDone({ content: '', sources: [] });
    });
    mockRequestOutline.mockResolvedValue({ title: 't', headings: [{ title: 'A', level: 1 }] });
  });

  test('passes the group reranker + search settings into research', async () => {
    render(
      <BriefTab
        dataSource="wfp"
        rerankerModel="vertex-ai-ranker"
        searchSettings={{ denseWeight: 0.7, fieldBoost: true }}
      />,
    );
    // Logged-in users land on Brief Central: open the New-brief modal, name the
    // brief and generate the outline from there.
    fireEvent.click(screen.getByText('New brief'));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'cash assistance' } });
    fireEvent.click(screen.getByText('Generate outline'));

    await waitFor(() => expect(mockRunDeepResearch).toHaveBeenCalled());
    const arg = mockRunDeepResearch.mock.calls[0][0];
    expect(arg.rerankerModel).toBe('vertex-ai-ranker');
    expect(arg.searchSettings).toMatchObject({ denseWeight: 0.7, fieldBoost: true });
  });
});
