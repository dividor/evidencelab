import React from 'react';
import axios from 'axios';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { HeatmapTabContent } from '../components/app/HeatmapTabContent';
import { Facets } from '../types/api';

// The real FiltersPanel is rendered here: these tests exercise the side
// filters (checkboxes, "Clear filters") that feed the heatmap's cell requests.
jest.mock('../components/SearchResultsList', () => ({
  SearchResultsList: () => <div>Search Results</div>,
}));

const GENERATE_HEATMAP = 'Generate Heatmap';
const TUNE_QUERY = /Tune your heatmap using a search query/;
const GRID_QUERY_PLACEHOLDER = 'Add a search query to filter the results for your heatmap ...';

const buildFacets = (): Facets => ({
  facets: {
    published_year: [{ value: '2024', count: 5 }],
    document_type: [{ value: 'IAHE', count: 2 }, { value: 'Activity', count: 3 }],
    country: [{ value: 'Kenya', count: 4 }],
  },
  filter_fields: {
    published_year: 'Year Published',
    document_type: 'Document Type',
    country: 'Country',
  },
});

const noop = () => undefined;
const baseProps = {
  selectedDomain: 'wfp',
  loadingConfig: false,
  facetsDataSource: 'wfp',
  filtersExpanded: true,
  onToggleFiltersExpanded: noop,
  onClearFilters: jest.fn(),
  facets: buildFacets(),
  filters: {},
  selectedFilters: {},
  collapsedFilters: new Set<string>(),
  expandedFilterLists: new Set<string>(),
  filterSearchTerms: {},
  titleSearchResults: [],
  facetSearchResults: {},
  onRemoveFilter: noop,
  onToggleFilter: noop,
  onFilterSearchTermChange: noop,
  onToggleFilterListExpansion: noop,
  onFilterValuesChange: noop,
  searchModel: null,
  searchDenseWeight: 0.8,
  onSearchDenseWeightChange: noop,
  keywordBoostShortQueries: true,
  onKeywordBoostChange: noop,
  semanticHighlighting: true,
  onSemanticHighlightingChange: noop,
  minScore: 0,
  maxScore: 1,
  onMinScoreChange: noop,
  rerankEnabled: false,
  onRerankToggle: noop,
  recencyBoostEnabled: false,
  onRecencyBoostToggle: noop,
  recencyWeight: 0.15,
  onRecencyWeightChange: noop,
  recencyScaleDays: 365,
  onRecencyScaleDaysChange: noop,
  rerankModel: null,
  rerankModelPageSize: null,
  minChunkSize: 0,
  onMinChunkSizeChange: noop,
  sectionTypes: [],
  onSectionTypesChange: noop,
  autoMinScore: false,
  onAutoMinScoreToggle: noop,
  deduplicateEnabled: true,
  onDeduplicateToggle: noop,
  wideSearch: false,
  onWideSearchToggle: noop,
  wideGroupSize: 5,
  onWideGroupSizeChange: noop,
  wideLimit: 20,
  onWideLimitChange: noop,
  groupByDocument: false,
  onGroupByDocumentToggle: noop,
  summaryLimitResults: true,
  onSummaryLimitResultsChange: noop,
  summaryMaxResults: 20,
  onSummaryMaxResultsChange: noop,
  summaryTemperature: 0,
  onSummaryTemperatureChange: noop,
  fieldBoostEnabled: false,
  onFieldBoostToggle: noop,
  fieldBoostFields: {},
  onFieldBoostFieldsChange: noop,
  selectedModelCombo: 'Azure Foundry',
  dataSource: 'wfp',
  selectedDoc: null,
  onResultClick: noop,
  onOpenMetadata: noop,
  onLanguageChange: noop,
};

const cellRequestParams = (getSpy: jest.SpyInstance) =>
  getSpy.mock.calls
    .map(([url]) => String(url))
    .filter((url) => /\/(doc)?search\?/.test(url))
    .map((url) => new URLSearchParams(url.split('?')[1]));

const openCountryFilter = () => {
  // Filter sections start collapsed; the header toggles the checkbox list.
  const header = screen.getAllByText('Country').find((el) => el.classList.contains('filter-section-title'));
  fireEvent.click(header!.parentElement as HTMLElement);
};

const setGridQuery = (value: string) => {
  fireEvent.click(screen.getByRole('button', { name: TUNE_QUERY }));
  fireEvent.change(screen.getByPlaceholderText(GRID_QUERY_PLACEHOLDER), { target: { value } });
};

const cellTexts = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('td.heatmap-cell')).map((cell) => cell.textContent);

const resultsWithScores = (scores: number[]) => ({
  data: {
    results: scores.map((score, index) => ({
      chunk_id: `c${index}`,
      doc_id: `d${index}`,
      text: '',
      page_num: 1,
      headings: [],
      score,
      title: `Doc ${index}`,
      year: '2024',
      organization: 'WFP',
    })),
  },
});

describe('Heatmap side filters', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/heatmap');
  });

  test('a side-panel selection is sent with every cell request and "Clear filters" removes it', async () => {
    const getSpy = jest.spyOn(axios, 'get').mockResolvedValue({ data: { results: [] } });
    const postSpy = jest.spyOn(axios, 'post').mockResolvedValue({ data: {} });
    try {
      render(<HeatmapTabContent {...baseProps} />);
      await waitFor(() => expect(screen.getByText('2024')).toBeInTheDocument());

      openCountryFilter();
      const kenya = screen.getByLabelText(/Kenya/) as HTMLInputElement;
      fireEvent.click(kenya);
      expect(kenya.checked).toBe(true);

      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(cellRequestParams(getSpy).length).toBeGreaterThan(0));
      await waitFor(() => expect(screen.getByRole('button', { name: GENERATE_HEATMAP })).toBeEnabled());
      for (const params of cellRequestParams(getSpy)) {
        expect(params.get('country')).toBe('Kenya');
      }
      getSpy.mockClear();

      // Regression: the button used to clear only the parent's copy of the
      // filters, so the next run still sent country=Kenya.
      fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
      expect(baseProps.onClearFilters).toHaveBeenCalled();
      expect((screen.getByLabelText(/Kenya/) as HTMLInputElement).checked).toBe(false);

      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(cellRequestParams(getSpy).length).toBeGreaterThan(0));
      for (const params of cellRequestParams(getSpy)) {
        expect(params.get('country')).toBeNull();
      }
    } finally {
      getSpy.mockRestore();
      postSpy.mockRestore();
    }
  });

  test('the sensitivity cutoff survives a filter-only re-run and resets when the query changes', async () => {
    // Run 1: scores 0.9/0.5/0.1 → auto cutoff 0.74 → one document per cell.
    // Run 2 (filter only): scores 0.5/0.4 → nothing above 0.74 → empty cells.
    // Run 3 (new query): same scores → cutoff recomputed (0.48) → one document.
    let scores = [0.9, 0.5, 0.1];
    const getSpy = jest.spyOn(axios, 'get').mockImplementation((url) =>
      /\/search\?/.test(String(url))
        ? Promise.resolve(resultsWithScores(scores))
        : Promise.resolve({ data: [] })
    );
    const postSpy = jest.spyOn(axios, 'post').mockResolvedValue({ data: {} });
    try {
      const { container } = render(<HeatmapTabContent {...baseProps} />);
      await waitFor(() => expect(screen.getByText('2024')).toBeInTheDocument());
      setGridQuery('girls education');

      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(cellTexts(container)).toEqual(['1', '1']));

      scores = [0.5, 0.4];
      openCountryFilter();
      fireEvent.click(screen.getByLabelText(/Kenya/));
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(screen.getByRole('button', { name: GENERATE_HEATMAP })).toBeEnabled());
      await waitFor(() => expect(cellTexts(container)).toEqual(['0', '0']));

      scores = [0.5, 0.4];
      fireEvent.change(screen.getByPlaceholderText(GRID_QUERY_PLACEHOLDER), { target: { value: 'school feeding' } });
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(cellTexts(container)).toEqual(['1', '1']));
    } finally {
      getSpy.mockRestore();
      postSpy.mockRestore();
    }
  });

  test('the sensitivity moved by hand is kept for a filter-only re-run', async () => {
    const getSpy = jest.spyOn(axios, 'get').mockImplementation((url) =>
      /\/search\?/.test(String(url))
        ? Promise.resolve(resultsWithScores([0.9, 0.5, 0.1]))
        : Promise.resolve({ data: [] })
    );
    const postSpy = jest.spyOn(axios, 'post').mockResolvedValue({ data: {} });
    try {
      const { container } = render(<HeatmapTabContent {...baseProps} />);
      await waitFor(() => expect(screen.getByText('2024')).toBeInTheDocument());
      setGridQuery('girls education');
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(cellTexts(container)).toEqual(['1', '1']));

      // The slider is inverted (right = more results); its value maps to a
      // cutoff of min + max - value. Move it to include every result.
      const slider = container.querySelector('#heatmap-cutoff') as HTMLInputElement;
      fireEvent.change(slider, { target: { value: String(0.9 + 0.1 - 0.05) } });
      await waitFor(() => expect(cellTexts(container)).toEqual(['3', '3']));

      openCountryFilter();
      fireEvent.click(screen.getByLabelText(/Kenya/));
      fireEvent.click(screen.getByRole('button', { name: GENERATE_HEATMAP }));
      await waitFor(() => expect(screen.getByRole('button', { name: GENERATE_HEATMAP })).toBeEnabled());
      expect(cellTexts(container)).toEqual(['3', '3']);
    } finally {
      getSpy.mockRestore();
      postSpy.mockRestore();
    }
  });
});
