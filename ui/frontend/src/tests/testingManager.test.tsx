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
    window.history.replaceState(null, '', '/admin');
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
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Datasets' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Experiments' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Datasets' }));
    expect(screen.getByRole('heading', {name: 'Experiment datasets'})).toBeVisible();
    await waitFor(() => expect(screen.getByText('Search Smoke')).toBeInTheDocument());
    expect(mockedAxios.get).toHaveBeenCalledWith(
      expect.stringContaining('/testing/datasets'),
      expect.anything()
    );
  });

  test('switching to the Experiments sub-view fetches experiments', async () => {
    render(<TestingManager />);
    fireEvent.click(screen.getByRole('button', {name:'Datasets'}));
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
    expect(screen.getByRole('button', { name: 'Experiments' })).toHaveClass('btn-primary');
    const newBtn = await screen.findByRole('button', { name: /New Experiment/i });
    fireEvent.click(newBtn);
    // The experiment editor (where per-row assertions + config live) renders.
    await waitFor(() => expect(screen.getByText(/Run as group/i)).toBeInTheDocument());
  });
});

test('the CSV example is available with its matching import action', async () => {
  render(<TestingManager />);
  fireEvent.click(screen.getByRole('button', {name:'Datasets'}));
  await screen.findByText('Search Smoke');
  expect(screen.queryByText(/example CSV/i)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'New dataset' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Import from CSV' }));
  const download = screen.getByRole('link', { name: 'Download example CSV' });
  expect(download).toHaveAttribute('download', 'qa-experiment-sample.csv');
  expect(decodeURIComponent(download.getAttribute('href') || '')).toContain('expectation');
});

test('restores a dataset from the API and keeps its filter when opening experiments', async () => {
  window.history.replaceState(null, '', '/admin?admin_page=testing&admin_dataset=d1');
  mockedAxios.get.mockImplementation(async url => {
    if (url.endsWith('/datasets/d1')) return { data: {...datasets[0], capability:'brief'} };
    if (url.endsWith('/datasets')) return { data: datasets };
    return { data: [] };
  });
  render(<TestingManager />);
  expect(await screen.findByRole('heading', {name:'Brief templates'})).toBeVisible();
  fireEvent.click(screen.getByRole('button', {name:'View experiments'}));
  expect(await screen.findByText(/Experiments for "Search Smoke"/)).toBeVisible();
  expect(new URLSearchParams(window.location.search).get('admin_dataset')).toBe('d1');
});

test('a deleted dataset link explains the failure and can return to the list', async () => {
  window.history.replaceState(null, '', '/admin?admin_page=testing&admin_dataset=deleted');
  mockedAxios.get.mockImplementation(async url => {
    if (url.endsWith('/deleted')) throw new Error('Not found');
    return { data: datasets };
  });
  render(<TestingManager />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not open this dataset');
  fireEvent.click(screen.getByRole('button', {name:'Back to datasets'}));
  expect(await screen.findByText('Search Smoke')).toBeVisible();
});

test('reload of an experiment edit URL loads the saved configuration', async () => {
  window.history.replaceState(null, '', '/admin?admin_page=testing&admin_testing=experiments&admin_experiment=e1&admin_mode=edit');
  mockedAxios.get.mockImplementation(async url => {
    if (url.endsWith('/experiments/e1')) return { data: {
      id: 'e1', dataset_id: 'd1', name: 'Search review', config: {}, case_expectations: {},
    } };
    if (url.endsWith('/datasets')) return { data: datasets };
    return { data: [] };
  });
  render(<TestingManager />);
  expect(await screen.findByDisplayValue('Search review')).toBeVisible();
});
