import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import axios from 'axios';

import { PDFViewer } from '../components/PDFViewer';

jest.mock('axios');

const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('PDFViewer', () => {
  test('renders error state when PDF load fails', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { highlights: [] } });
    window.pdfjsLib = {
      getDocument: () => {
        throw new Error('boom');
      },
      renderTextLayer: jest.fn(),
      GlobalWorkerOptions: {},
    };

    const onClose = jest.fn();
    render(
      <PDFViewer docId="doc-1" chunkId="chunk-1" onClose={onClose} />
    );

    expect(await screen.findByText('Failed to load PDF: boom')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Close'));
    expect(onClose).toHaveBeenCalled();
  });
});
