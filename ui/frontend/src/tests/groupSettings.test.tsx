import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import GroupSettingsManager from '../components/admin/GroupSettingsManager';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.mock('../../src/config', () => ({
  __esModule: true,
  default: '/api',
}));

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

const SEL_INPUT_TYPE_CHECKBOX = 'input[type="checkbox"]';
const SEARCH_SETTINGS = 'Search Settings';
const SAVE_SETTINGS = 'Save Settings';

const URL_API_GROUPS_G2 = '/api/groups/g2';

describe('GroupSettingsManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.get.mockResolvedValue({ data: mockGroups });
  });

  test('renders group chips after loading', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });
    expect(screen.getByText('Default (Default)')).toBeInTheDocument();
  });

  test('auto-selects default group and shows settings panel', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText(SEARCH_SETTINGS)).toBeInTheDocument();
      expect(screen.getByText('Content Settings')).toBeInTheDocument();
    });
  });

  test('loads group search_settings values into controls', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });

    // Click the Analysts chip to select it
    fireEvent.click(screen.getByText('Analysts'));

    await waitFor(() => {
      expect(screen.getByText(SEARCH_SETTINGS)).toBeInTheDocument();
    });

    // Analysts group has rerank=false, so the Enable Reranker checkbox should be unchecked
    const rerankLabel = screen.getByText('Enable Reranker');
    const rerankCheckbox = rerankLabel.parentElement!.querySelector(SEL_INPUT_TYPE_CHECKBOX) as HTMLInputElement;
    expect(rerankCheckbox.checked).toBe(false);
  });

  test('save button calls PATCH with only overridden keys', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[0] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Analysts'));

    await waitFor(() => {
      expect(screen.getByText(SAVE_SETTINGS)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(SAVE_SETTINGS));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: expect.objectContaining({ denseWeight: 0.5, rerank: false }),
        summary_prompt: '',
      });
    });
  });

  test('reset button sends empty search_settings', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[0], search_settings: null } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Analysts'));

    await waitFor(() => {
      expect(screen.getByText('Reset to Defaults')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Reset to Defaults'));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: {},
        summary_prompt: '',
      });
    });
  });

  test('shows loading state initially', () => {
    mockedAxios.get.mockReturnValue(new Promise(() => {})); // Never resolves
    render(<GroupSettingsManager />);
    expect(screen.getByText('Loading groups...')).toBeInTheDocument();
  });

  test('changing a setting marks it as overridden in save payload', async () => {
    // Default group (g2) is auto-selected and has no overrides (search_settings: null)
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText(SEARCH_SETTINGS)).toBeInTheDocument();
    });

    // Toggle the Deduplicate checkbox (currently true by default)
    const deduplicateLabel = screen.getByText('Deduplicate');
    const deduplicateCheckbox = deduplicateLabel.parentElement!.querySelector(SEL_INPUT_TYPE_CHECKBOX) as HTMLInputElement;
    fireEvent.click(deduplicateCheckbox);

    fireEvent.click(screen.getByText(SAVE_SETTINGS));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { deduplicate: false },
        summary_prompt: '',
      });
    });
  });

  test('wide search and its fields are saved as group overrides', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText(SEARCH_SETTINGS)).toBeInTheDocument();
    });

    const wideLabel = screen.getByText('Wide Search');
    const wideCheckbox = wideLabel.parentElement!.querySelector(SEL_INPUT_TYPE_CHECKBOX) as HTMLInputElement;
    fireEvent.click(wideCheckbox);
    fireEvent.change(screen.getByLabelText('Max results per document'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Number of documents'), { target: { value: '40' } });

    fireEvent.click(screen.getByText(SAVE_SETTINGS));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { wideSearch: true, wideGroupSize: 3, wideLimit: 40 },
        summary_prompt: '',
      });
    });
  });

  test('the AI summary result cap is saved as group overrides', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('AI Summary')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Max results for summary'), { target: { value: '35' } });
    const limitLabel = screen.getByText('Limit Results Used');
    fireEvent.click(limitLabel.parentElement!.querySelector(SEL_INPUT_TYPE_CHECKBOX) as HTMLInputElement);

    fireEvent.click(screen.getByText(SAVE_SETTINGS));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { summaryMaxResults: 35, summaryLimitResults: false },
        summary_prompt: '',
      });
    });
  });

  test('the AI summary temperature is saved as a group override', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('AI Summary')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText('Creativity'), { target: { value: '0.5' } });
    fireEvent.click(screen.getByText(SAVE_SETTINGS));
    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { summaryTemperature: 0.5 },
        summary_prompt: '',
      });
    });
  });
});
