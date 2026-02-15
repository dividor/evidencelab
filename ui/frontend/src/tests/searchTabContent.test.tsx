import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { SearchTabContent } from '../components/app/SearchTabContent';
import { SearchResult } from '../types/api';

jest.mock('../components/AiSummaryPanel', () => ({
  AiSummaryPanel: () => <div>AI Summary</div>,
}));

jest.mock('../components/filters/FiltersPanel', () => ({
  FiltersPanel: () => <div>Filters Panel</div>,
}));

jest.mock('../components/SearchResultsList', () => ({
  SearchResultsList: ({ results }: { results: SearchResult[] }) => (
    <div data-testid="results-list">
      {results.map((r) => (
        <div key={r.chunk_id} data-testid={`result-${r.chunk_id}`}>
          {r.title}
        </div>
      ))}
    </div>
  ),
}));

const buildResult = (overrides: Partial<SearchResult> = {}): SearchResult => ({
  chunk_id: 'chunk-1',
  doc_id: 'doc-1',
  text: 'Sample text',
  page_num: 1,
  headings: [],
  score: 0.9,
  title: 'Report A',
  organization: 'UNICEF',
  year: '2023',
  metadata: {},
  ...overrides,
});

const baseProps = {
  filtersExpanded: false,
  activeFiltersCount: 0,
  onToggleFiltersExpanded: jest.fn(),
  onClearFilters: jest.fn(),
  facets: null,
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
  searchDenseWeight: 0.8,
  onSearchDenseWeightChange: jest.fn(),
  keywordBoostShortQueries: true,
  onKeywordBoostChange: jest.fn(),
  semanticHighlighting: true,
  onSemanticHighlightingChange: jest.fn(),
  minScore: 0,
  maxScore: 1,
  onMinScoreChange: jest.fn(),
  autoMinScore: false,
  onAutoMinScoreToggle: jest.fn(),
  rerankEnabled: false,
  onRerankToggle: jest.fn(),
  recencyBoostEnabled: false,
  onRecencyBoostToggle: jest.fn(),
  recencyWeight: 0.15,
  onRecencyWeightChange: jest.fn(),
  recencyScaleDays: 365,
  onRecencyScaleDaysChange: jest.fn(),
  minChunkSize: 100,
  onMinChunkSizeChange: jest.fn(),
  sectionTypes: [] as string[],
  onSectionTypesChange: jest.fn(),
  deduplicateEnabled: false,
  onDeduplicateToggle: jest.fn(),
  aiSummaryEnabled: false,
  aiSummaryCollapsed: false,
  aiSummaryExpanded: false,
  aiSummaryLoading: false,
  aiSummary: '',
  aiSummaryResults: [] as SearchResult[],
  aiPrompt: '',
  showPromptModal: false,
  selectedDomain: 'uneg',
  results: [] as SearchResult[],
  loading: false,
  query: 'test',
  selectedDoc: null,
  onResultClick: jest.fn(),
  onOpenPrompt: jest.fn(),
  onClosePrompt: jest.fn(),
  onToggleCollapsed: jest.fn(),
  onToggleExpanded: jest.fn(),
  onOpenMetadata: jest.fn(),
  onLanguageChange: jest.fn(),
};

describe('SearchTabContent result filters', () => {
  test('does not show filters when there is only one unique document', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF', page_num: 2 }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    expect(document.querySelector('.search-result-filters')).not.toBeInTheDocument();
  });

  test('shows document thumbnails when multiple unique documents exist', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    expect(document.querySelector('.search-result-filters')).toBeInTheDocument();
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    expect(thumbnails).toHaveLength(2);
  });

  test('shows org labels when multiple orgs exist', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    expect(screen.getByText('UNICEF (1)')).toBeInTheDocument();
    expect(screen.getByText('WFP (1)')).toBeInTheDocument();
  });

  test('does not show org labels when all results share the same org', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'UNICEF' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    expect(document.querySelector('.search-result-filters-orgs')).not.toBeInTheDocument();
    // Thumbnails should still be present
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    expect(thumbnails).toHaveLength(2);
  });

  test('clicking an org label filters thumbnails to that org', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
      buildResult({ chunk_id: 'c3', doc_id: 'doc-3', title: 'Report C', organization: 'UNICEF' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    // All 3 thumbnails visible initially
    expect(document.querySelectorAll('.search-result-filters-thumbnail')).toHaveLength(3);

    // Click UNICEF org filter
    fireEvent.click(screen.getByText('UNICEF (2)'));

    // Only UNICEF docs should show
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    expect(thumbnails).toHaveLength(2);
    const thumbTitles = document.querySelectorAll('.search-result-filters-thumbnail-title');
    expect(thumbTitles[0].textContent).toBe('Report A');
    expect(thumbTitles[1].textContent).toBe('Report C');
  });

  test('clicking a document thumbnail filters results to that document', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    // Click thumbnail for Report A
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    fireEvent.click(thumbnails[0]);

    // Should show filter indicator
    expect(screen.getByText('Report A', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText('× Clear filter')).toBeInTheDocument();

    // Only Report A should be in the results list
    expect(screen.getByTestId('result-c1')).toBeInTheDocument();
    expect(screen.queryByTestId('result-c2')).not.toBeInTheDocument();
  });

  test('clicking clear filter resets all filters', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    // Click a thumbnail to activate filter
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    fireEvent.click(thumbnails[0]);
    expect(screen.queryByTestId('result-c2')).not.toBeInTheDocument();

    // Click clear
    fireEvent.click(screen.getByText('× Clear filter'));

    // Both results visible again
    expect(screen.getByTestId('result-c1')).toBeInTheDocument();
    expect(screen.getByTestId('result-c2')).toBeInTheDocument();
  });

  test('clicking an active org label toggles it off', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    const unicefBtn = screen.getByText('UNICEF (1)');

    // Activate
    fireEvent.click(unicefBtn);
    expect(unicefBtn).toHaveClass('active');

    // Deactivate
    fireEvent.click(unicefBtn);
    expect(unicefBtn).not.toHaveClass('active');
    expect(document.querySelectorAll('.search-result-filters-thumbnail')).toHaveLength(2);
  });

  test('clicking a selected thumbnail toggles it off', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');

    // Select
    fireEvent.click(thumbnails[0]);
    expect(thumbnails[0]).toHaveClass('selected');

    // Deselect
    fireEvent.click(thumbnails[0]);
    expect(thumbnails[0]).not.toHaveClass('selected');
    expect(screen.getByTestId('result-c1')).toBeInTheDocument();
    expect(screen.getByTestId('result-c2')).toBeInTheDocument();
  });

  test('results below minScore are excluded from filter computation', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', score: 0.8 }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', score: 0.3 }),
    ];

    render(<SearchTabContent {...baseProps} results={results} minScore={0.5} />);

    // Only 1 unique doc above threshold, so filters should not show
    expect(document.querySelector('.search-result-filters')).not.toBeInTheDocument();
  });

  test('documents are sorted by result frequency', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Rare Report', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Popular Report', organization: 'WFP' }),
      buildResult({ chunk_id: 'c3', doc_id: 'doc-2', title: 'Popular Report', organization: 'WFP', page_num: 2 }),
      buildResult({ chunk_id: 'c4', doc_id: 'doc-2', title: 'Popular Report', organization: 'WFP', page_num: 3 }),
    ];

    render(<SearchTabContent {...baseProps} results={results} />);

    const titles = document.querySelectorAll('.search-result-filters-thumbnail-title');
    expect(titles[0].textContent).toBe('Popular Report');
    expect(titles[1].textContent).toBe('Rare Report');
  });

  test('semantic highlight updates do not reset active filter', () => {
    const results = [
      buildResult({ chunk_id: 'c1', doc_id: 'doc-1', title: 'Report A', organization: 'UNICEF' }),
      buildResult({ chunk_id: 'c2', doc_id: 'doc-2', title: 'Report B', organization: 'WFP' }),
    ];

    const { rerender } = render(<SearchTabContent {...baseProps} results={results} />);

    // Activate a document filter
    const thumbnails = document.querySelectorAll('.search-result-filters-thumbnail');
    fireEvent.click(thumbnails[0]);
    expect(screen.queryByTestId('result-c2')).not.toBeInTheDocument();

    // Simulate semantic highlighting: new array, same chunk_ids, mutated properties
    const highlightedResults = results.map((r) => ({
      ...r,
      semanticMatches: [{ start: 0, end: 5, matchedText: 'test' }],
    }));
    rerender(<SearchTabContent {...baseProps} results={highlightedResults} />);

    // Filter should still be active
    expect(screen.queryByTestId('result-c2')).not.toBeInTheDocument();
    expect(screen.getByTestId('result-c1')).toBeInTheDocument();
  });
});
