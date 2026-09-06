import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

import { HeatmapTabContent } from '../components/app/HeatmapTabContent';
import { Facets } from '../types/api';

jest.mock('../components/filters/FiltersPanel', () => ({
  FiltersPanel: () => <div>Filters Panel</div>,
}));

jest.mock('../components/SearchResultsList', () => ({
  SearchResultsList: () => <div>Search Results</div>,
}));

const buildFacets = (): Facets => ({
  facets: {
    published_year: [{ value: '2020', count: 5 }],
    document_type: [{ value: 'Report', count: 3 }],
  },
  filter_fields: {
    published_year: 'Publication Year',
    document_type: 'Document Type',
  },
});

const baseProps = {
  selectedDomain: 'wfp',
  loadingConfig: false,
  facetsDataSource: 'wfp',
  filtersExpanded: false,
  activeFiltersCount: 0,
  onToggleFiltersExpanded: jest.fn(),
  onClearFilters: jest.fn(),
  facets: buildFacets(),
  filters: {},
  selectedFilters: {},
  collapsedFilters: new Set<string>(),
  expandedFilterLists: new Set<string>(),
  filterSearchTerms: {},
  titleSearchResults: [],
  facetSearchResults: {},
  onRemoveFilter: jest.fn(),
  onToggleFilter: jest.fn(),
  onFilterSearchTermChange: jest.fn(),
  onToggleFilterListExpansion: jest.fn(),
  onFilterValuesChange: jest.fn(),
  searchModel: null,
  searchDenseWeight: 0.8,
  onSearchDenseWeightChange: jest.fn(),
  keywordBoostShortQueries: true,
  onKeywordBoostChange: jest.fn(),
  semanticHighlighting: true,
  onSemanticHighlightingChange: jest.fn(),
  minScore: 0,
  maxScore: 1,
  onMinScoreChange: jest.fn(),
  rerankEnabled: true,
  onRerankToggle: jest.fn(),
  recencyBoostEnabled: false,
  onRecencyBoostToggle: jest.fn(),
  recencyWeight: 0.15,
  onRecencyWeightChange: jest.fn(),
  recencyScaleDays: 365,
  onRecencyScaleDaysChange: jest.fn(),
  rerankModel: null,
  rerankModelPageSize: null,
  minChunkSize: 100,
  onMinChunkSizeChange: jest.fn(),
  sectionTypes: ['executive_summary'],
  onSectionTypesChange: jest.fn(),
  autoMinScore: false,
  onAutoMinScoreToggle: jest.fn(),
  deduplicateEnabled: false,
  onDeduplicateToggle: jest.fn(),
  fieldBoostEnabled: false,
  onFieldBoostToggle: jest.fn(),
  fieldBoostFields: {},
  onFieldBoostFieldsChange: jest.fn(),
  selectedModelCombo: 'Azure Foundry',
  dataSource: 'wfp',
  selectedDoc: null,
  onResultClick: jest.fn(),
  onOpenMetadata: jest.fn(),
  onLanguageChange: jest.fn(),
};

const GENERATE_HEATMAP = 'Generate Heatmap';

describe('HeatmapTabContent', () => {
  test('renders defaults and enables Generate Heatmap for dimension rows without query', async () => {
    render(<HeatmapTabContent {...baseProps} />);

    await waitFor(() => {
      expect(screen.getByText('2020')).toBeInTheDocument();
    });

    const rowSelect = screen.getByLabelText('Rows') as HTMLSelectElement;
    const columnSelect = screen.getByLabelText('Columns') as HTMLSelectElement;
    const metricSelect = screen.getByLabelText('Metric') as HTMLSelectElement;
    expect(rowSelect.value).toBe('document_type');
    expect(columnSelect.value).toBe('published_year');
    expect(metricSelect.value).toBe('documents');

    // Dimension vs dimension: button enabled even without a query
    const searchButton = screen.getByRole('button', { name: GENERATE_HEATMAP });
    expect(searchButton).toBeEnabled();
  });

  test('switching to Search query rows hides grid query input', async () => {
    render(<HeatmapTabContent {...baseProps} />);

    await waitFor(() => {
      expect(screen.getByText('2020')).toBeInTheDocument();
    });

    const rowSelect = screen.getByLabelText('Rows');
    fireEvent.change(rowSelect, { target: { value: 'queries' } });

    const rowInputs = screen.getAllByPlaceholderText('Enter your search query');
    expect(rowInputs).toHaveLength(1);

    const searchButton = screen.getByRole('button', { name: GENERATE_HEATMAP });
    expect(searchButton).toBeDisabled();

    fireEvent.change(rowInputs[0], { target: { value: 'climate' } });
    expect(searchButton).toBeEnabled();
  });

  test('the Generate button gets an × while generating that stops the run', async () => {
    const isCellRequest = (url: unknown) => /\/(doc)?search\?/.test(String(url));
    // Cell requests only settle when their signal is aborted, like a slow backend.
    const getSpy = jest.spyOn(axios, 'get').mockImplementation((url, config) => {
      if (!isCellRequest(url)) return Promise.resolve({ data: [] });
      return new Promise((_, reject) => {
        config?.signal?.addEventListener('abort', () =>
          reject(new axios.CanceledError('canceled')),
        );
      });
    });
    const postSpy = jest.spyOn(axios, 'post').mockResolvedValue({ data: {} });
    try {
      const { container } = render(<HeatmapTabContent {...baseProps} />);
      await waitFor(() => expect(screen.getByText('2020')).toBeInTheDocument());

      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));

      const stop = await screen.findByRole('button', { name: 'Stop generating' });
      // The Generate button itself is disabled and reads "Generating..." (one
      // animated span per character, so match its text rather than its name).
      const generating = container.querySelector('.heatmap-search-button') as HTMLButtonElement;
      expect(generating).toBeDisabled();
      expect(generating.textContent).toBe('Generating...');
      const cellCalls = getSpy.mock.calls.filter(([url]) => isCellRequest(url));
      expect(cellCalls.length).toBeGreaterThan(0);
      const { signal } = cellCalls[0][1] as { signal: AbortSignal };
      expect(signal.aborted).toBe(false);

      fireEvent.click(stop);

      expect(signal.aborted).toBe(true);
      await waitFor(() =>
        expect(screen.getByRole('button', { name: GENERATE_HEATMAP })).toBeEnabled(),
      );
      expect(screen.queryByRole('button', { name: 'Stop generating' })).toBeNull();
      // A stop is not a failure: no error message.
      expect(screen.queryByText(/failed to load|search failed/i)).toBeNull();
    } finally {
      getSpy.mockRestore();
      postSpy.mockRestore();
    }
  });
});
