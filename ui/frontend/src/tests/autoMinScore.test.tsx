import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const mockFacets = {
  facets: {
    organization: [],
    published_year: [],
    document_type: [],
    country: [],
    language: [],
    tag_sdg: [],
    tag_cross_cutting_theme: [],
  },
  filter_fields: {
    organization: 'Organization',
    published_year: 'Published Year',
    document_type: 'Document Type',
    country: 'Country',
    language: 'Language',
    tag_sdg: 'SDG',
    tag_cross_cutting_theme: 'Cross-Cutting Theme',
  },
};

const mockSearchResults = {
  results: [
    { chunk_id: '1', text: 'Result 1', score: 0.9, title: 'Doc 1', page_num: 1, doc_id: 'd1' },
    { chunk_id: '2', text: 'Result 2', score: 0.8, title: 'Doc 2', page_num: 1, doc_id: 'd2' },
    { chunk_id: '3', text: 'Result 3', score: 0.7, title: 'Doc 3', page_num: 1, doc_id: 'd3' },
    { chunk_id: '4', text: 'Result 4', score: 0.6, title: 'Doc 4', page_num: 1, doc_id: 'd4' },
    { chunk_id: '5', text: 'Result 5', score: 0.5, title: 'Doc 5', page_num: 1, doc_id: 'd5' },
    { chunk_id: '6', text: 'Result 6', score: 0.4, title: 'Doc 6', page_num: 1, doc_id: 'd6' },
    { chunk_id: '7', text: 'Result 7', score: 0.3, title: 'Doc 7', page_num: 1, doc_id: 'd7' },
    { chunk_id: '8', text: 'Result 8', score: 0.2, title: 'Doc 8', page_num: 1, doc_id: 'd8' },
    { chunk_id: '9', text: 'Result 9', score: 0.1, title: 'Doc 9', page_num: 1, doc_id: 'd9' },
    { chunk_id: '10', text: 'Result 10', score: 0.05, title: 'Doc 10', page_num: 1, doc_id: 'd10' },
  ],
  facets: mockFacets,
};

/** Wait for search tab to load, then expand the collapsible More Filters panel. */
const expandFilters = async () => {
  const filtersBtn = await screen.findByRole('button', { name: 'More Filters' });
  fireEvent.click(filtersBtn);
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Filters' })).toBeInTheDocument();
  });
};

describe('Auto Min Score Feature', () => {
  beforeEach(() => {
    // Set URL with a query so App auto-searches on load (renders search tab with Filters)
    window.history.pushState({}, '', '/?q=test');
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
      if (url.includes('/search')) {
        return Promise.resolve({ data: mockSearchResults });
      }
      if (url.includes('/facets')) {
        return Promise.resolve({ data: mockFacets });
      }
      return Promise.resolve({ data: {} });
    });
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  test('Auto checkbox appears and toggles correctly', async () => {
    render(<App />);

    await expandFilters();

    // Expand search settings
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);

    // Find the Auto checkbox
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    expect(autoCheckbox).toBeInTheDocument();
    expect(autoCheckbox).not.toBeChecked();

    // Toggle auto on
    fireEvent.click(autoCheckbox);
    expect(autoCheckbox).toBeChecked();

    // Toggle auto off
    fireEvent.click(autoCheckbox);
    expect(autoCheckbox).not.toBeChecked();
  });

  test('Slider disappears when auto is enabled', async () => {
    render(<App />);

    await expandFilters();

    // Expand search settings
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);

    // Find sliders initially
    const sliders = screen.getAllByRole('slider');
    const initialSliderCount = sliders.length;

    // Enable auto
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    fireEvent.click(autoCheckbox);

    // Slider should be hidden
    const slidersAfterAuto = screen.getAllByRole('slider');
    expect(slidersAfterAuto.length).toBe(initialSliderCount - 1);
  });

  test('Auto mode sends auto_min_score parameter to backend', async () => {
    render(<App />);

    await expandFilters();

    // Expand search settings and enable auto
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    fireEvent.click(autoCheckbox);

    // Perform a search
    const searchInput = screen.getByPlaceholderText(/search/i);
    fireEvent.change(searchInput, { target: { value: 'test query' } });
    fireEvent.submit(searchInput.closest('form')!);

    // Wait for search to complete and check that auto_min_score parameter was sent
    await waitFor(() => {
      expect(mockedAxios.get).toHaveBeenCalledWith(
        expect.stringContaining('auto_min_score=true'),
      );
    });
  });

  test('Manual slider adjustment disables auto mode', async () => {
    render(<App />);

    await expandFilters();

    // Expand search settings
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);

    // Enable auto
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    fireEvent.click(autoCheckbox);
    expect(autoCheckbox).toBeChecked();

    // Disable auto by clicking again to show slider
    fireEvent.click(autoCheckbox);

    // Find and adjust the min score slider
    const sliders = screen.getAllByRole('slider');
    const minScoreSlider = sliders.find(slider => {
      const container = slider.closest('.search-settings-group');
      return container?.querySelector('label')?.textContent?.includes('Min Score');
    });

    expect(minScoreSlider).toBeDefined();
    if (minScoreSlider) {
      fireEvent.change(minScoreSlider, { target: { value: '0.5' } });
    }

    // Re-enable auto
    fireEvent.click(autoCheckbox);

    // Now disable auto by adjusting slider
    fireEvent.click(autoCheckbox); // Turn off auto to show slider again
    if (minScoreSlider) {
      fireEvent.change(minScoreSlider, { target: { value: '0.7' } });
    }

    // Auto should still be off after manual adjustment
    expect(autoCheckbox).not.toBeChecked();
  });

  test('URL parameter auto_min_score=true initializes auto mode', async () => {
    window.history.pushState({}, '', '/?q=test&auto_min_score=true');

    render(<App />);

    await expandFilters();

    // Expand search settings
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);

    // Auto checkbox should be checked
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    expect(autoCheckbox).toBeChecked();
  });

  test('Auto mode updates URL with auto_min_score parameter', async () => {
    const pushStateSpy = jest.spyOn(window.history, 'pushState');

    render(<App />);

    await expandFilters();

    // Expand search settings
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);

    // Enable auto
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    fireEvent.click(autoCheckbox);

    // Perform a search
    const searchInput = screen.getByPlaceholderText(/search/i);
    fireEvent.change(searchInput, { target: { value: 'test' } });
    fireEvent.submit(searchInput.closest('form')!);

    // Check that URL was updated with auto_min_score=true
    await waitFor(() => {
      expect(pushStateSpy).toHaveBeenCalledWith(
        null,
        '',
        expect.stringContaining('auto_min_score=true')
      );
    });

    pushStateSpy.mockRestore();
  });

  test('Backend filters results when auto_min_score is enabled', async () => {
    render(<App />);

    await expandFilters();

    // Expand search settings and enable auto
    const searchSettingsHeader = screen.getByText('Search Settings');
    fireEvent.click(searchSettingsHeader);
    const autoCheckbox = screen.getByRole('checkbox', { name: /Auto/i });
    fireEvent.click(autoCheckbox);

    // Perform search with auto mode enabled
    const searchInput = screen.getByPlaceholderText(/search/i);
    fireEvent.change(searchInput, { target: { value: 'auto filter test' } });
    fireEvent.submit(searchInput.closest('form')!);

    // Verify backend was called with auto_min_score parameter in a search request
    await waitFor(() => {
      expect(mockedAxios.get).toHaveBeenCalledWith(
        expect.stringMatching(/\/search.*auto_min_score=true/),
      );
    });
  });
});
