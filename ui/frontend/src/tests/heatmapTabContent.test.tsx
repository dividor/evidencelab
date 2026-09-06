import React from 'react';
import axios from 'axios';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { HeatmapTabContent } from '../components/app/HeatmapTabContent';
import { Facets } from '../types/api';

jest.mock('../components/filters/FiltersPanel', () => ({
  FiltersPanel: () => <div>Filters Panel</div>,
}));

jest.mock('../components/SearchResultsList', () => ({
  SearchResultsList: () => <div>Search Results</div>,
}));

const GENERATE_HEATMAP = 'Generate Heatmap';
const GRID_QUERY_PLACEHOLDER = 'Add a search query to filter the results for your heatmap ...';

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
  wideSearch: false,
  onWideSearchToggle: jest.fn(),
  wideGroupSize: 5,
  onWideGroupSizeChange: jest.fn(),
  wideLimit: 20,
  onWideLimitChange: jest.fn(),
  groupByDocument: false,
  onGroupByDocumentToggle: jest.fn(),
  summaryLimitResults: true,
  onSummaryLimitResultsChange: jest.fn(),
  summaryMaxResults: 20,
  onSummaryMaxResultsChange: jest.fn(),
  summaryTemperature: 0,
  onSummaryTemperatureChange: jest.fn(),
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

describe('HeatmapTabContent', () => {
  // The component reads its initial state from the URL and writes back to it,
  // so each test starts from a clean address.
  beforeEach(() => {
    window.history.replaceState(null, '', '/heatmap');
  });

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

  test('with wide search on, every cell request carries the per-document cap and the cell limit as document cap', async () => {
    const getSpy = jest.spyOn(axios, 'get').mockResolvedValue({ data: { results: [] } });
    const postSpy = jest.spyOn(axios, 'post').mockResolvedValue({ data: {} });
    try {
      render(<HeatmapTabContent {...baseProps} wideSearch wideGroupSize={3} />);
      await waitFor(() => expect(screen.getByText('2020')).toBeInTheDocument());
      // No query: cells list documents by filter alone, which has no relevance
      // ranking, so wide search must not be sent there.
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(getSpy).toHaveBeenCalled());
      const listingUrls = getSpy.mock.calls.map(([url]) => String(url)).filter((u) => u.includes('/docsearch?'));
      expect(listingUrls.length).toBeGreaterThan(0);
      for (const url of listingUrls) {
        expect(url).not.toContain('wide_search');
      }
      getSpy.mockClear();

      // With a query, every cell is a relevance search and carries wide search
      fireEvent.click(screen.getByRole('button', { name: /Tune your heatmap using a search query/ }));
      fireEvent.change(screen.getByPlaceholderText(GRID_QUERY_PLACEHOLDER), { target: { value: 'school feeding' } });
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(getSpy).toHaveBeenCalled());
      const cellUrls = getSpy.mock.calls.map(([url]) => String(url)).filter((u) => u.includes('/search?'));
      expect(cellUrls.length).toBeGreaterThan(0);
      for (const url of cellUrls) {
        const params = new URLSearchParams(url.split('?')[1]);
        expect(params.get('wide_search')).toBe('true');
        expect(params.get('wide_group_size')).toBe('3');
        expect(params.get('wide_limit')).toBe(params.get('limit'));
      }
    } finally {
      getSpy.mockRestore();
      postSpy.mockRestore();
    }
  });
});
