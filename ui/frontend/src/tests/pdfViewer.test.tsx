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

  test('opens the document with eval turned off', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { highlights: [] } });
    const getDocument = jest.fn(() => ({
      promise: Promise.reject(new Error('stop after the call')),
    }));
    window.pdfjsLib = {
      getDocument,
      renderTextLayer: jest.fn(),
      GlobalWorkerOptions: {},
    };

    render(<PDFViewer docId="doc-1" chunkId="chunk-1" onClose={jest.fn()} />);

    await screen.findByText('Failed to load PDF: stop after the call');
    expect(getDocument).toHaveBeenCalledTimes(1);
    expect(getDocument).toHaveBeenCalledWith(
      expect.objectContaining({ isEvalSupported: false })
    );
    expect(getDocument.mock.calls[0][0].url).toMatch(/\/pdf\/doc-1\?data_source=/);
  });
});
