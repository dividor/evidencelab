import React from 'react';
import { render, screen } from '@testing-library/react';
import axios from 'axios';

import LogsModal from '../components/LogsModal';

jest.mock('axios');

const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.setTimeout(20000);

describe('LogsModal', () => {
  beforeEach(() => {
    mockedAxios.get.mockReset();
  });

  test('renders logs from the API', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { logs: 'Log output' } });

    render(
      <LogsModal
        isOpen={true}
        onClose={jest.fn()}
        docId="doc-1"
        docTitle="Title"
        dataSource="uneg"
      />
    );

    expect(await screen.findByText('Log output')).toBeInTheDocument();
    expect(mockedAxios.get).toHaveBeenCalledWith(
      expect.stringContaining('/document/doc-1/logs'),
      expect.any(Object)
    );
  });

  test('renders error from the API', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { error: 'No logs' } });

    render(
      <LogsModal
        isOpen={true}
        onClose={jest.fn()}
        docId="doc-2"
        docTitle="Title"
        dataSource="uneg"
      />
    );

    expect(await screen.findByText('Error:')).toBeInTheDocument();
    expect(screen.getByText('No logs')).toBeInTheDocument();
  });
});
