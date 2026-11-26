import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import GroupSettingsManager from '../components/admin/GroupSettingsManager';
import { llmChoicePayload, readLlmChoices } from '../components/admin/LlmChoiceGroupSection';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.mock('../../src/config', () => ({
  __esModule: true,
  default: '/api',
}));

const group = (search_settings: Record<string, unknown> | null) => ({
  id: 'g1',
  name: 'Analysts',
  description: '',
  is_default: true,
  created_at: '2026-01-01T00:00:00Z',
  datasource_keys: [],
  member_count: 3,
  search_settings,
});

const NOVA_LITE = 'nova-2-lite';
const SONNET = 'sonnet-5.5';

const LLMS = [
  { name: NOVA_LITE, model: 'eu.amazon.nova-2-lite-v1:0', provider: 'aws_bedrock', supports_temperature: true },
  { name: 'nova-pro', model: 'eu.amazon.nova-pro-v1:0', provider: 'aws_bedrock', supports_temperature: true },
  { name: SONNET, model: 'eu.example.sonnet', provider: 'aws_bedrock', supports_temperature: false },
];
const DEFAULTS = { summary: NOVA_LITE, brief: NOVA_LITE, judge: 'nova-pro', citation_check: NOVA_LITE };

const serve = (settings: Record<string, unknown> | null) => {
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.endsWith('/config/llms')) return Promise.resolve({ data: LLMS });
    if (url.endsWith('/config/llm-defaults')) return Promise.resolve({ data: DEFAULTS });
    return Promise.resolve({ data: [group(settings)] });
  });
};

const openLlmsTab = async () => {
  fireEvent.click(await screen.findByRole('tab', { name: 'LLMs' }));
  await screen.findByText('Default from config (nova-pro)');
};

describe('Group Settings > LLMs', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('lists the offered models after a default naming config.json\'s model', async () => {
    serve(null);
    render(<GroupSettingsManager />);
    await openLlmsTab();

    const summary = screen.getByLabelText('Search AI summary') as HTMLSelectElement;
    expect(summary.value).toBe('');
    expect(Array.from(summary.options).map((o) => o.textContent)).toEqual([
      'Default from config (nova-2-lite)',
      NOVA_LITE,
      'nova-pro',
      'sonnet-5.5 (ignores Response variability)',
    ]);
    expect(screen.getByText('Default from config (nova-pro)')).toBeInTheDocument();
    expect(screen.getByLabelText('Automatic citation check')).toHaveValue('');
  });

  test('saves the chosen models with the group settings', async () => {
    serve({ rerank: false });
    mockedAxios.patch.mockResolvedValue({ data: group(null) });
    render(<GroupSettingsManager />);
    await openLlmsTab();

    fireEvent.change(screen.getByLabelText('Search AI summary'), { target: { value: 'nova-pro' } });
    fireEvent.change(screen.getByLabelText('Evaluation judge'), { target: { value: SONNET } });
    fireEvent.change(screen.getByLabelText('Automatic citation check'), { target: { value: 'nova-pro' } });
    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() =>
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: { rerank: false, summaryModel: 'nova-pro', judgeModel: SONNET, citationCheckModel: 'nova-pro' },
        summary_prompt: '',
      }),
    );
  });

  test('a saved choice the site no longer offers is shown and flagged', async () => {
    serve({ briefModel: 'retired-model' });
    render(<GroupSettingsManager />);
    await openLlmsTab();

    expect((screen.getByLabelText('Brief') as HTMLSelectElement).value).toBe('retired-model');
    expect(screen.getByRole('alert')).toHaveTextContent('This site no longer offers retired-model');
  });

  test('read and payload keep only the chosen jobs', () => {
    expect(readLlmChoices({ summaryModel: 'nova-pro', briefModel: '' })).toEqual({
      summaryModel: 'nova-pro',
      briefModel: undefined,
      judgeModel: undefined,
      citationCheckModel: undefined,
    });
    expect(llmChoicePayload({ summaryModel: 'nova-pro', judgeModel: undefined })).toEqual({
      summaryModel: 'nova-pro',
    });
  });
});
