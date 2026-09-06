import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// USER_MODULE on + an authenticated user => the brief is "logged in".
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));
jest.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'u1' } }) }));

// Brief Central (logged-in landing) loads briefs/templates/voices over axios.
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: jest.fn().mockResolvedValue({ data: [] }),
    post: jest.fn().mockResolvedValue({ data: {} }),
    put: jest.fn().mockResolvedValue({ data: {} }),
    delete: jest.fn().mockResolvedValue({ data: {} }),
  },
}));

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
