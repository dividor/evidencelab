import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import axios from 'axios';

import { PDFViewer } from '../components/PDFViewer';
import { loadPdfjs } from '../utils/pdfjsLoader';

jest.mock('axios');
jest.mock('../utils/pdfjsLoader', () => {
  const actual = jest.requireActual('../utils/pdfjsLoader');
  return { ...actual, loadPdfjs: jest.fn(actual.loadPdfjs) };
});

const mockedAxios = axios as jest.Mocked<typeof axios>;
const mockedLoadPdfjs = loadPdfjs as jest.MockedFunction<typeof loadPdfjs>;

const fakePdfjs = (getDocument: jest.Mock) => ({
  getDocument,
  TextLayer: jest.fn(() => ({ render: jest.fn().mockResolvedValue(undefined) })),
  GlobalWorkerOptions: {},
});

describe('PDFViewer', () => {
  afterEach(() => {
    delete (window as any).pdfjsLib;
  });

  test('renders error state when PDF load fails', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { highlights: [] } });
    window.pdfjsLib = fakePdfjs(
      jest.fn(() => {
        throw new Error('boom');
      })
    );

    const onClose = jest.fn();
    render(
      <PDFViewer docId="doc-1" chunkId="chunk-1" onClose={onClose} />
    );

    expect(await screen.findByText('Failed to load PDF: boom')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Close'));
    expect(onClose).toHaveBeenCalled();
  });

  test('opens the document without WebAssembly, with decoders from this site', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { highlights: [] } });
    const getDocument = jest.fn(() => ({
      promise: Promise.reject(new Error('stop after the call')),
    }));
    window.pdfjsLib = fakePdfjs(getDocument);

    render(<PDFViewer docId="doc-1" chunkId="chunk-1" onClose={jest.fn()} />);

    await screen.findByText('Failed to load PDF: stop after the call');
    expect(getDocument).toHaveBeenCalledTimes(1);
    const options = getDocument.mock.calls[0][0] as any;
    expect(options.url).toMatch(/\/pdf\/doc-1\?data_source=/);
    expect(options.useWasm).toBe(false);
    expect(options.wasmUrl).toMatch(/\/pdfjs\/[^/]+\/$/);
    expect(options.wasmUrl.startsWith(window.location.origin)).toBe(true);
  });

  test('shows an error when PDF.js cannot be loaded', async () => {
    mockedAxios.get.mockResolvedValueOnce({ data: { highlights: [] } });
    mockedLoadPdfjs.mockRejectedValueOnce(new Error('offline'));
    jest.spyOn(console, 'error').mockImplementation(() => undefined);

    render(<PDFViewer docId="doc-1" chunkId="chunk-1" onClose={jest.fn()} />);

    expect(await screen.findByText('Failed to load PDF.js library')).toBeInTheDocument();
  });
});
