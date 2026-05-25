// Coverage for the in-document search request shape. Specifically:
//   1. The /search request is scoped by `doc_id`, not by the tokenized
//      `title` filter — otherwise other documents sharing title tokens
//      would leak chunks into the result set.
//   2. The `min_score` sent to the backend is max(PDF_SEARCH_SEMANTIC_CUTOFF,
//      the user's minScore slider) — so any client-side stricter setting
//      still applies, but always through the single backend authority that
//      honors `include_exact_matches`.
//   3. `include_exact_matches` is always true for in-doc search.
//
// Mocks pdfjsLib and axios; drives the search via the in-doc input box.

import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react';
import axios from 'axios';

import { PDFViewer } from '../components/PDFViewer';
import { PDF_SEARCH_SEMANTIC_CUTOFF } from '../config';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const stubCanvasContext = () => {
  HTMLCanvasElement.prototype.getContext = jest.fn(() =>
    ({ canvas: document.createElement('canvas') } as unknown as CanvasRenderingContext2D)
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
};

const buildPdfMocks = (numPages = 1) => {
  const pageMock = {
    getViewport: ({ scale }: { scale: number }) => ({
      scale,
      width: 600,
      height: 800,
    }),
    getTextContent: () => Promise.resolve({ items: [] }),
    render: () => ({
      promise: Promise.resolve(),
      cancel: jest.fn(),
    }),
  };
  const pdfDoc = {
    numPages,
    getPage: jest.fn(() => Promise.resolve(pageMock)),
  };
  return {
    getDocument: () => ({ promise: Promise.resolve(pdfDoc) }),
    renderTextLayer: jest.fn(() => Promise.resolve()),
    GlobalWorkerOptions: {},
  };
};

const renderViewer = (props: Partial<React.ComponentProps<typeof PDFViewer>> = {}) =>
  render(
    <PDFViewer
      docId="doc-abc-123"
      chunkId="chunk-1"
      pageNum={1}
      onClose={jest.fn()}
      title="Cambodia Evaluation Report 2023"
      searchQuery="climate"
      dataSource="wfp"
      {...props}
    />,
  );

const findSearchCall = () => {
  // axios.get is called both for the in-doc /search request and for ancillary
  // calls (e.g. /document/<id> for TOC). Pick the /search invocation.
  const call = mockedAxios.get.mock.calls.find((c) =>
    typeof c[0] === 'string' && (c[0] as string).endsWith('/search'),
  );
  if (!call) {
    throw new Error('Expected a GET /search call but none was made');
  }
  return call;
};

const triggerInDocSearch = (container: HTMLElement, query: string) => {
  const input = container.querySelector(
    'input.pdf-search-input',
  ) as HTMLInputElement | null;
  if (!input) {
    throw new Error('In-doc search input not found');
  }
  fireEvent.change(input, { target: { value: query } });
  fireEvent.keyPress(input, { key: 'Enter', code: 'Enter', charCode: 13 });
};

describe('PDFViewer in-document search request params', () => {
  beforeEach(() => {
    (global as any).MockIntersectionObserver.reset();
    stubCanvasContext();
    window.pdfjsLib = buildPdfMocks(1);
    mockedAxios.get.mockResolvedValue({ data: { results: [] } });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('scopes by doc_id (not title) so cross-document title leakage is impossible', async () => {
    const { container } = renderViewer();

    await waitFor(() => {
      expect(container.querySelector('input.pdf-search-input')).not.toBeNull();
    });

    triggerInDocSearch(container, 'monsoon flooding');

    await waitFor(() => {
      // findSearchCall throws if no /search call was made.
      findSearchCall();
    });

    const [, opts] = findSearchCall();
    const params = (opts as { params: Record<string, unknown> }).params;

    expect(params.doc_id).toBe('doc-abc-123');
    expect(params).not.toHaveProperty('title');
    expect(params.include_exact_matches).toBe('true');
  });

  test('sends min_score = max(PDF_SEARCH_SEMANTIC_CUTOFF, user minScore slider)', async () => {
    // User dialed minScore well above the in-doc cutoff. The request should
    // carry the stricter value, not the cutoff floor.
    const stricterMinScore = PDF_SEARCH_SEMANTIC_CUTOFF + 0.25;
    const { container } = renderViewer({ minScore: stricterMinScore });

    await waitFor(() => {
      expect(container.querySelector('input.pdf-search-input')).not.toBeNull();
    });

    triggerInDocSearch(container, 'monsoon flooding');

    await waitFor(() => {
      findSearchCall();
    });

    const [, opts] = findSearchCall();
    const params = (opts as { params: Record<string, unknown> }).params;

    expect(parseFloat(params.min_score as string)).toBeCloseTo(stricterMinScore, 5);
  });

  test('falls back to PDF_SEARCH_SEMANTIC_CUTOFF when minScore is 0', async () => {
    const { container } = renderViewer({ minScore: 0 });

    await waitFor(() => {
      expect(container.querySelector('input.pdf-search-input')).not.toBeNull();
    });

    triggerInDocSearch(container, 'monsoon flooding');

    await waitFor(() => {
      findSearchCall();
    });

    const [, opts] = findSearchCall();
    const params = (opts as { params: Record<string, unknown> }).params;

    expect(parseFloat(params.min_score as string)).toBeCloseTo(
      PDF_SEARCH_SEMANTIC_CUTOFF,
      5,
    );
  });
});
