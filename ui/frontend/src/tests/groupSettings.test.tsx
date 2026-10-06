import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
const SEARCH_AI_SUMMARY = 'Search AI Summary';
const DOC_SUMMARIES = 'Document Summaries';

const URL_API_GROUPS_G2 = '/api/groups/g2';

describe('GroupSettingsManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.get.mockResolvedValue({ data: mockGroups });
  });

  test('settings are on tabs, one area at a time, and Save covers every tab', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });
    render(<GroupSettingsManager />);
    const searchTab = await screen.findByRole('tab', { name: SEARCH_SETTINGS });
    expect(searchTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      SEARCH_SETTINGS,
      'Content Settings',
      SEARCH_AI_SUMMARY,
      'Brief',
      DOC_SUMMARIES,
      'Features & Tabs',
      'Appearance',
    ]);
    expect(screen.getByText('Enable Reranker')).toBeInTheDocument();
    expect(screen.queryByLabelText('Max results for summary')).toBeNull();

    // A change on one tab survives moving to another, and Save sends both.
    const rerank = screen.getByText('Enable Reranker').parentElement!.querySelector(SEL_INPUT_TYPE_CHECKBOX) as HTMLInputElement;
    fireEvent.click(rerank);
    fireEvent.click(screen.getByRole('tab', { name: SEARCH_AI_SUMMARY }));
    expect(screen.queryByText('Enable Reranker')).toBeNull();
    fireEvent.change(screen.getByLabelText('Max results for summary'), { target: { value: '35' } });
    expect(screen.getByRole('tab', { name: SEARCH_AI_SUMMARY })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByText(SAVE_SETTINGS));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { rerank: false, summaryMaxResults: 35 },
        summary_prompt: '',
      });
    });
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
    fireEvent.click(await screen.findByRole('tab', { name: SEARCH_AI_SUMMARY }));

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
    fireEvent.click(await screen.findByRole('tab', { name: SEARCH_AI_SUMMARY }));
    fireEvent.change(screen.getByLabelText('Response variability'), { target: { value: '0.5' } });
    fireEvent.click(screen.getByText(SAVE_SETTINGS));
    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
        search_settings: { summaryTemperature: 0.5 },
        summary_prompt: '',
      });
    });
  });

  describe('Document Summaries', () => {
    const DEFAULT_PROMPT = 'OUTPUT FORMAT (you must only use these headings): ...';
    const USE_SOURCE_SECTIONS = "Use the data source's sections";
    const mockGets = (groups = mockGroups) =>
      mockedAxios.get.mockImplementation(async (url: string) =>
        url.startsWith('/api/document-summaries/settings')
          ? {
              data: {
                prompt: DEFAULT_PROMPT,
                modes: ['map_reduce', 'single_prompt'],
                all_section_types: ['executive_summary', 'findings', 'annexes'],
                data_sources: [
                  { key: 'wfp', name: 'WFP Evaluation Reports', mode: 'map_reduce', section_types: ['executive_summary', 'findings', 'annexes'] },
                  { key: 'wb', name: 'World Bank', mode: 'single_prompt', section_types: ['findings'] },
                ],
              },
            }
          : { data: groups },
      );

    const openSection = async () => {
      fireEvent.click(await screen.findByRole('tab', { name: DOC_SUMMARIES }));
      const section = within(screen.getByRole('tabpanel'));
      await waitFor(() => expect(section.getByLabelText(USE_SOURCE_SECTIONS)).toBeEnabled());
      return section;
    };

    test("shows each data source's mode and sections, and the prompt ready to edit", async () => {
      mockGets();
      render(<GroupSettingsManager />);
      const section = await openSection();

      expect(section.getByLabelText(/Data source's mode/)).toBeChecked();
      expect(section.getByText('WFP Evaluation Reports: Map reduce · World Bank: Single prompt')).toBeInTheDocument();
      const chips = (name: string) =>
        Array.from(section.getByText(name).parentElement!.querySelectorAll('.doc-summary-chip')).map((c) => c.textContent);
      expect(chips('WFP Evaluation Reports')).toEqual(['Executive summary', 'Findings', 'Annexes']);
      expect(chips('World Bank')).toEqual(['Findings']);
      expect(section.getByLabelText('Team summary prompt')).toHaveValue(DEFAULT_PROMPT);
      expect(section.getByRole('button', { name: 'Reset to default' })).toBeDisabled();
    });

    test('mode, sections and prompt are saved as group defaults', async () => {
      mockGets();
      mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });
      render(<GroupSettingsManager />);
      const section = await openSection();

      fireEvent.click(section.getByLabelText(/^Single prompt/));
      fireEvent.click(section.getByLabelText(USE_SOURCE_SECTIONS));
      fireEvent.click(section.getByLabelText('Annexes'));
      fireEvent.change(section.getByLabelText('Team summary prompt'), { target: { value: 'Three bullet points.' } });
      expect(section.getByRole('button', { name: 'Reset to default' })).toBeEnabled();
      fireEvent.click(screen.getByText(SAVE_SETTINGS));

      await waitFor(() => {
        expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
          search_settings: {
            docSummaryMode: 'single_prompt',
            docSummarySectionTypes: ['executive_summary', 'findings'],
            docSummaryPrompt: 'Three bullet points.',
          },
          summary_prompt: '',
        });
      });
    });

    test("a group's saved defaults load, and can be put back to the data source's", async () => {
      const groups = [
        mockGroups[0],
        {
          ...mockGroups[1],
          search_settings: { docSummaryMode: 'map_reduce', docSummarySectionTypes: ['findings'], docSummaryPrompt: 'Mine.' },
        },
      ];
      mockGets(groups);
      mockedAxios.patch.mockResolvedValue({ data: groups[1] });
      render(<GroupSettingsManager />);
      const section = await openSection();

      expect(section.getByLabelText(/^Map reduce/)).toBeChecked();
      expect(section.getByLabelText('Findings')).toBeChecked();
      expect(section.getByLabelText('Annexes')).not.toBeChecked();
      expect(section.getByLabelText('Team summary prompt')).toHaveValue('Mine.');

      fireEvent.click(section.getByLabelText(/Data source's mode/));
      fireEvent.click(section.getByLabelText(USE_SOURCE_SECTIONS));
      fireEvent.click(section.getByRole('button', { name: 'Reset to default' }));
      expect(section.getByLabelText('Team summary prompt')).toHaveValue(DEFAULT_PROMPT);
      fireEvent.click(screen.getByText(SAVE_SETTINGS));

      await waitFor(() => {
        expect(mockedAxios.patch).toHaveBeenCalledWith(URL_API_GROUPS_G2, {
          search_settings: {},
          summary_prompt: '',
        });
      });
    });

    test('typing the default prompt back counts as no custom prompt', async () => {
      mockGets();
      mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[1] } });
      render(<GroupSettingsManager />);
      const section = await openSection();
      const box = section.getByLabelText('Team summary prompt');
      fireEvent.change(box, { target: { value: 'Changed' } });
      fireEvent.change(box, { target: { value: DEFAULT_PROMPT } });
      expect(section.getByRole('button', { name: 'Reset to default' })).toBeDisabled();
    });
  });
});
