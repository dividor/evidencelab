import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import GroupSettingsManager from '../components/admin/GroupSettingsManager';

jest.mock('axios');
jest.mock('../config', () => ({ __esModule: true, default: '/api' }));

test('loads and saves Assistant overrides independently of the AI Summary prompt', async () => {
  const mocked = axios as jest.Mocked<typeof axios>;
  const summary_prompt = 'Existing AI Summary instructions.';
  const group = {
    id: 'oev', name: 'OEV', is_default: true, member_count: 1, datasource_keys: [],
    search_settings: {
      rerank: true,
      assistant: { answerPrompt: 'Saved Assistant instructions.', searchesPerStream: 2 },
    },
    summary_prompt,
  };
  mocked.get.mockImplementation(async url => (
    url.endsWith('/config/llms')
      ? { data: [{ name: 'nova-2-lite', supports_temperature: true }] }
      : { data: [group] }
  ));
  mocked.patch.mockResolvedValue({ data: group });

  render(<GroupSettingsManager />);
  fireEvent.click(await screen.findByRole('tab', { name: 'Assistant', exact: true }));
  expect(screen.getByLabelText('Answer prompt')).toHaveValue('Saved Assistant instructions.');
  expect(screen.getByLabelText('Assistant searches per stream')).toHaveValue(2);
  await screen.findByRole('option', { name: 'nova-2-lite' });
  const controls = {
    Model: 'nova-2-lite',
    'Response variability': '0.2',
    'Maximum output tokens': '2500',
    'Starting research mode': 'deep',
    'Planning prompt': 'Verify the reported coverage.',
    'Answer prompt': 'Separate findings by country.',
    'Deep Research searches per stream': '5',
  };
  Object.entries(controls).forEach(([label, value]) => {
    fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

  await waitFor(() => expect(mocked.patch).toHaveBeenCalledWith('/api/groups/oev', {
    summary_prompt,
    search_settings: {
      rerank: true,
      assistant: {
        model: 'nova-2-lite', temperature: 0.2, maxTokens: 2500, deepResearchByDefault: true,
        planningPrompt: 'Verify the reported coverage.', answerPrompt: 'Separate findings by country.',
        searchesPerStream: 2, deepSearchesPerStream: 5,
      },
    },
  }));
});
