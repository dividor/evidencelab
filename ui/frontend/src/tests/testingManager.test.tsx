import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

import TestingManager from '../components/admin/TestingManager';

const datasets = [
  {
    id: 'd1',
    name: 'Search Smoke',
    capability: 'search',
    data_source: 'uneg',
    created_at: '2026-06-14T00:00:00Z',
    updated_at: '2026-06-14T00:00:00Z',
    num_cases: 3,
    last_pass_rate: 0.8,
  },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/cases')) return Promise.resolve({ data: [] });
    if (url.includes('/testing/datasets')) return Promise.resolve({ data: datasets });
    if (url.includes('/testing/experiments')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: [] });
  });
});

describe('TestingManager', () => {
  test('renders the datasets sub-view with fetched datasets', async () => {
    render(<TestingManager />);
    expect(screen.getByRole('button', { name: 'Datasets' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Experiments' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Search Smoke')).toBeInTheDocument());
    expect(mockedAxios.get).toHaveBeenCalledWith(
      expect.stringContaining('/testing/datasets'),
      expect.anything()
    );
  });

  test('switching to the Experiments sub-view fetches experiments', async () => {
    render(<TestingManager />);
    await waitFor(() => screen.getByText('Search Smoke'));
    fireEvent.click(screen.getByRole('button', { name: 'Experiments' }));
    await waitFor(() =>
      expect(mockedAxios.get).toHaveBeenCalledWith(
        expect.stringContaining('/testing/experiments'),
        expect.anything()
      )
    );
  });

  test('opening "New Experiment" shows the draft editor (assertions live here)', async () => {
    render(<TestingManager />);
    await waitFor(() => screen.getByText('Search Smoke'));
    fireEvent.click(screen.getByRole('button', { name: 'Experiments' }));
    const newBtn = await screen.findByRole('button', { name: /New Experiment/i });
    fireEvent.click(newBtn);
    // The experiment editor (where per-row assertions + config live) renders.
    await waitFor(() => expect(screen.getByText(/Run as group/i)).toBeInTheDocument());
  });
});
