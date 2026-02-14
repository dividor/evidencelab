import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

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
  minChunkSize: 100,
  onMinChunkSizeChange: jest.fn(),
  sectionTypes: ['executive_summary'],
  onSectionTypesChange: jest.fn(),
  dataSource: 'wfp',
  selectedDoc: null,
  onResultClick: jest.fn(),
  onOpenMetadata: jest.fn(),
  onLanguageChange: jest.fn(),
};

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
    const searchButton = screen.getByRole('button', { name: 'Generate Heatmap' });
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

    const searchButton = screen.getByRole('button', { name: 'Generate Heatmap' });
    expect(searchButton).toBeDisabled();

    fireEvent.change(rowInputs[0], { target: { value: 'climate' } });
    expect(searchButton).toBeEnabled();
  });
});
