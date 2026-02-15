import React from 'react';
import { fireEvent, render, screen, within, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';

jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', null, children),
  };
});

import App from '../App';

jest.mock('axios');
jest.mock('../components/Documents', () => ({
  Documents: () => <div>Documents View</div>,
}));
jest.mock('../components/Pipeline', () => ({
  Pipeline: () => <div>Pipeline View</div>,
  Processing: () => <div>Processing View</div>,
}));
jest.mock('../components/PDFViewer', () => ({
  PDFViewer: () => <div>PDF Viewer</div>,
}));
jest.mock('../components/TocModal', () => ({
  __esModule: true,
  default: () => <div>TOC Modal</div>,
}));
jest.mock('../components/SearchResultCard', () => ({
  __esModule: true,
  default: () => <div>Result Card</div>,
}));

const mockedAxios = axios as jest.Mocked<typeof axios>;
const TEST_SUMMARIZATION_MODEL = 'qwen2.5-7b-instruct';
const TEST_RERANKER_MODEL = 'jinaai/jina-reranker-v2-base-multilingual';

describe('App', () => {
  beforeEach(() => {
    // Reset mocks before each test - clears call history but keeps implementations
    jest.clearAllMocks();
    // Reset the URL
    window.history.pushState({}, '', '/');
  });

  afterEach(() => {
    // Clean up React components
    cleanup();
  });

  test('loads config and navigates tabs', async () => {
    mockedAxios.get.mockImplementation((url) => {
      if (url.includes('/config/datasources')) {
        return Promise.resolve({
          data: {
            'Test Source': {
              data_subdir: 'test',
              field_mapping: {},
              filter_fields: {},
            },
          },
        });
      }
      if (url.includes('/config/model-combos')) {
        return Promise.resolve({
          data: {
            'Test Combo': {
              embedding_model: 'e5_large',
              summarization_model: TEST_SUMMARIZATION_MODEL,
              reranker_model: TEST_RERANKER_MODEL,
            },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const pushStateSpy = jest.spyOn(window.history, 'pushState');
    window.history.pushState({}, '', '/');

    render(<App />);

    const nav = screen.getByRole('navigation');
    expect(within(nav).getByRole('button', { name: 'Search' })).toBeInTheDocument();
    fireEvent.click(within(nav).getByRole('button', { name: /Monitor/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Documents' }));

    expect(await screen.findByText('Documents View')).toBeInTheDocument();
    expect(pushStateSpy).toHaveBeenCalledWith(
      null,
      '',
      expect.stringContaining('/documents')
    );
  });

  test('uses selected model combo for search params', async () => {
    mockedAxios.get.mockImplementation((url) => {
      if (url.includes('/config/datasources')) {
        return Promise.resolve({
          data: {
            'Test Source': {
              data_subdir: 'test',
              field_mapping: {},
              filter_fields: {},
            },
          },
        });
      }
      if (url.includes('/config/model-combos')) {
        return Promise.resolve({
          data: {
            'Azure Foundry': {
              embedding_model: 'azure_small',
              summarization_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              semantic_highlighting_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              reranker_model: TEST_RERANKER_MODEL,
            },
            'Huggingface': {
              embedding_model: 'e5_large',
              summarization_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              semantic_highlighting_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              reranker_model: TEST_RERANKER_MODEL,
            },
            'Azure Foundry': {
              embedding_model: 'azure_small',
              summarization_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              semantic_highlighting_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              reranker_model: TEST_RERANKER_MODEL,
            },
            'Huggingface': {
              embedding_model: 'e5_large',
              summarization_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              semantic_highlighting_model: {
                model: TEST_SUMMARIZATION_MODEL,
                max_tokens: 500,
                temperature: 0.2,
                chunk_overlap: 800,
                chunk_tokens_ratio: 0.5,
              },
              reranker_model: TEST_RERANKER_MODEL,
            },
          },
        });
      }
      if (url.includes('/facets')) {
        return Promise.resolve({
          data: {
            facets: {},
            filter_fields: {},
          },
        });
      }
      if (url.includes('/search')) {
        return Promise.resolve({
          data: {
            results: [],
            total: 0,
            query: '',
            filters: {},
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(<App />);

    const nav = screen.getByRole('navigation');
    fireEvent.click(within(nav).getByRole('button', { name: 'Search' }));

    const modelButton = await screen.findByRole('button', { name: /Models/i });
    fireEvent.click(modelButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Huggingface' }));

    expect(await screen.findByRole('button', { name: /Models Huggingface/i })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Search documents'), {
      target: { value: 'test query' },
    });
    const searchButtons = screen.getAllByRole('button', { name: 'Search' });
    fireEvent.click(searchButtons[searchButtons.length - 1]);

    const searchCalls = mockedAxios.get.mock.calls
      .map(([callUrl]) => String(callUrl))
      .filter((callUrl) => callUrl.includes('/search?'));
    expect(searchCalls.length).toBeGreaterThan(0);
    const lastSearch = searchCalls[searchCalls.length - 1];
    expect(lastSearch).toContain('model=e5_large');
    expect(lastSearch).toContain('rerank_model=jinaai%2Fjina-reranker-v2-base-multilingual');
    expect(lastSearch).toContain('data_source=test');
  });

  // Note: This test is intended to run in isolation to avoid state pollution from other tests.
  // To run: npm test -- --testNamePattern="deep-links"
  test('deep-links to PDF modal with doc_id and chunk_id in URL', async () => {
    // Set up URL with query, dataset, and doc_id/chunk_id parameters
    window.history.pushState({}, '', '/?tab=search&q=test+query&dataset=Test+Source&doc_id=test-doc-123&chunk_id=test-chunk-456');

    const mockSearchResult = {
      chunk_id: 'test-chunk-456',
      doc_id: 'test-doc-123',
      text: 'This is test chunk content',
      page_num: 1,
      headings: ['Test Heading'],
      score: 0.95,
      title: 'Test Document',
      metadata: {},
    };

    const TEST_MODEL_CONFIG = {
      model: TEST_SUMMARIZATION_MODEL,
      max_tokens: 500,
      temperature: 0.2,
      chunk_overlap: 800,
      chunk_tokens_ratio: 0.5,
    };

    // Track if mock is set up correctly
    let configCallCount = 0;
    let wasSearchCalled = false;

    mockedAxios.get.mockImplementation((url) => {
      const urlStr = String(url);

      if (urlStr.includes('/config/datasources')) {
        configCallCount++;
        return Promise.resolve({
          data: {
            'Test Source': {
              data_subdir: 'test',
              field_mapping: {},
              filter_fields: {},
            },
          },
        });
      }
      if (urlStr.includes('/config/model-combos')) {
        configCallCount++;
        return Promise.resolve({
          data: {
            'Test Combo': {
              embedding_model: 'e5_large',
              summarization_model: TEST_MODEL_CONFIG,
              semantic_highlighting_model: TEST_MODEL_CONFIG,
              reranker_model: TEST_RERANKER_MODEL,
            },
          },
        });
      }
      if (urlStr.includes('/facets')) {
        return Promise.resolve({
          data: {
            facets: {},
            filter_fields: {},
          },
        });
      }
      if (urlStr.includes('/search')) {
        wasSearchCalled = true;
        return Promise.resolve({
          data: {
            results: [mockSearchResult],
            total: 1,
            query: 'test query',
            filters: {},
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const replaceStateSpy = jest.spyOn(window.history, 'replaceState');

    render(<App />);

    // Wait for configs to load first
    await waitFor(() => {
      expect(configCallCount).toBeGreaterThanOrEqual(2);
    }, { timeout: 2000 });

    // Wait for search to be called
    await waitFor(() => {
      expect(wasSearchCalled).toBe(true);
    }, { timeout: 5000 });

    // Wait for the PDF viewer to appear (modal auto-opens with matching result)
    expect(await screen.findByText('PDF Viewer', { timeout: 3000 })).toBeInTheDocument();

    // Verify the URL contains doc_id and chunk_id
    await waitFor(() => {
      expect(window.location.search).toContain('doc_id=test-doc-123');
      expect(window.location.search).toContain('chunk_id=test-chunk-456');
    });

    // Find the overlay element
    const overlay = document.querySelector('.preview-overlay');
    expect(overlay).toBeInTheDocument();

    // Close the modal by clicking the overlay
    if (overlay) {
      fireEvent.click(overlay);
    }

    // Wait for the modal to close
    await waitFor(() => {
      expect(screen.queryByText('PDF Viewer')).not.toBeInTheDocument();
    });

    // Verify that closing the modal removes doc_id and chunk_id from URL
    await waitFor(() => {
      const calls = replaceStateSpy.mock.calls;
      const hasCallWithoutDocId = calls.some(call => {
        const url = call[2] as string;
        return !url.includes('doc_id=');
      });
      expect(hasCallWithoutDocId).toBe(true);
    });

    // Check that query parameter is still present in the last call
    const lastCall = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1];
    const lastUrl = lastCall[2] as string;
    expect(lastUrl).toContain('q=test+query'); // Query should still be present
    expect(lastUrl).not.toContain('doc_id='); // doc_id should be removed
    expect(lastUrl).not.toContain('chunk_id='); // chunk_id should be removed
  });
});
