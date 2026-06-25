import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import ExperimentDetail from '../components/admin/testing/ExperimentDetail';

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
