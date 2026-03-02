import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.mock('../../src/config', () => ({
  __esModule: true,
  default: '/api',
}));

import GroupSettingsManager from '../components/admin/GroupSettingsManager';

const mockGroups = [
  {
    id: 'g1',
    name: 'Analysts',
    description: 'Analyst group',
    is_default: false,
    created_at: '2026-01-01T00:00:00Z',
    datasource_keys: [],
    member_count: 3,
    search_settings: { denseWeight: 0.5, rerank: false },
  },
  {
    id: 'g2',
    name: 'Default',
    description: 'Default Group',
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    datasource_keys: [],
    member_count: 10,
    search_settings: null,
  },
];

describe('GroupSettingsManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.get.mockResolvedValue({ data: mockGroups });
  });

  test('renders group dropdown after loading', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a group...')).toBeInTheDocument();
    });
    expect(screen.getByText('Analysts')).toBeInTheDocument();
    expect(screen.getByText('Default (Default)')).toBeInTheDocument();
  });

  test('shows settings panel when group is selected', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a group...')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'g1' } });

    await waitFor(() => {
      expect(screen.getByText('Search Settings')).toBeInTheDocument();
      expect(screen.getByText('Content Settings')).toBeInTheDocument();
    });
  });

  test('loads overrides from group search_settings', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a group...')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'g1' } });

    await waitFor(() => {
      expect(screen.getByText('Search Settings')).toBeInTheDocument();
    });

    // Analysts group has denseWeight=0.5 and rerank=false overridden
    // The override checkboxes for these should be checked
    const overrideCheckboxes = screen.getAllByRole('checkbox');
    // Find the "Search Mode" override checkbox (first one in the list)
    const denseWeightOverride = overrideCheckboxes[0];
    expect(denseWeightOverride).toBeChecked();
  });

  test('save button calls PATCH with only overridden keys', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[0] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a group...')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'g1' } });

    await waitFor(() => {
      expect(screen.getByText('Save Settings')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: expect.objectContaining({ denseWeight: 0.5, rerank: false }),
      });
    });
  });

  test('reset button sends empty search_settings', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[0], search_settings: null } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a group...')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'g1' } });

    await waitFor(() => {
      expect(screen.getByText('Reset to Defaults')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Reset to Defaults'));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: {},
      });
    });
  });

  test('shows loading state initially', () => {
    mockedAxios.get.mockReturnValue(new Promise(() => {})); // Never resolves
    render(<GroupSettingsManager />);
    expect(screen.getByText('Loading groups...')).toBeInTheDocument();
  });
});
