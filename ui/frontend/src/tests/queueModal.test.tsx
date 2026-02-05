import React from 'react';
import { render, screen } from '@testing-library/react';
import axios from 'axios';

import QueueModal from '../components/QueueModal';

jest.mock('axios');

const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.setTimeout(20000);

describe('QueueModal', () => {
  test('renders empty task sections', async () => {
    const emptyResponse = {
      data: { active: {}, reserved: {}, scheduled: {} },
    };
    mockedAxios.get.mockResolvedValueOnce(emptyResponse).mockResolvedValue(emptyResponse);

    render(<QueueModal isOpen={true} onClose={jest.fn()} />);

    expect(await screen.findByText('Task Queue Status')).toBeInTheDocument();
    expect(await screen.findByText('No active tasks')).toBeInTheDocument();
    expect(screen.getByText('No reserved tasks')).toBeInTheDocument();
    expect(screen.getByText('No scheduled tasks')).toBeInTheDocument();
  });

  test('renders task output when provided', async () => {
    const taskResponse = {
      data: {
        active: {
          worker: [
            {
              id: 'task-1',
              name: 'pipeline.utilities.tasks.reprocess_document',
              args: ['doc-1'],
              kwargs: {},
              output: 'Finished',
            },
          ],
        },
        reserved: {},
        scheduled: {},
      },
    };
    mockedAxios.get.mockResolvedValueOnce(taskResponse).mockResolvedValue(taskResponse);

    render(<QueueModal isOpen={true} onClose={jest.fn()} />);

    expect(await screen.findByText('Finished')).toBeInTheDocument();
  });
});
