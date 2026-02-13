import React from 'react';
import { Facets, FacetValue, SearchResult } from '../../types/api';
import { AiSummaryPanel } from '../AiSummaryPanel';
import { FiltersPanel } from '../filters/FiltersPanel';
import { MobileFiltersToggle } from '../MobileFiltersToggle';
import { SearchResultsList } from '../SearchResultsList';

interface SearchTabContentProps {
  filtersExpanded: boolean;
  activeFiltersCount: number;
  onToggleFiltersExpanded: () => void;
  onClearFilters: () => void;
  facets: Facets | null;
  selectedFilters: Record<string, string[]>;
  collapsedFilters: Set<string>;
  expandedFilterLists: Set<string>;
  filterSearchTerms: Record<string, string>;
  titleSearchResults: FacetValue[];
  facetSearchResults: Record<string, FacetValue[]>;
  onRemoveFilter: (coreField: string, value: string) => void;
  onToggleFilter: (coreField: string) => void;
  onFilterSearchTermChange: (coreField: string, value: string) => void;
  onToggleFilterListExpansion: (coreField: string) => void;
  onFilterValuesChange: (coreField: string, nextValues: string[]) => void;
  searchDenseWeight: number;
  onSearchDenseWeightChange: (value: number) => void;
  keywordBoostShortQueries: boolean;
  onKeywordBoostChange: (value: boolean) => void;
  semanticHighlighting: boolean;
  onSemanticHighlightingChange: (value: boolean) => void;
  minScore: number;
  maxScore: number;
  onMinScoreChange: (value: number) => void;
  autoMinScore: boolean;
  onAutoMinScoreToggle: (value: boolean) => void;
  rerankEnabled: boolean;
  onRerankToggle: (value: boolean) => void;
  recencyBoostEnabled: boolean;
  onRecencyBoostToggle: (value: boolean) => void;
  recencyWeight: number;
  onRecencyWeightChange: (value: number) => void;
  recencyScaleDays: number;
  onRecencyScaleDaysChange: (value: number) => void;
  minChunkSize: number;
  onMinChunkSizeChange: (value: number) => void;
  sectionTypes: string[];
  onSectionTypesChange: (next: string[]) => void;
  aiSummaryEnabled: boolean;
  aiSummaryCollapsed: boolean;
  aiSummaryExpanded: boolean;
  aiSummaryLoading: boolean;
  aiSummary: string;
  aiPrompt: string;
  showPromptModal: boolean;
  results: SearchResult[];
  loading: boolean;
  query: string;
  selectedDoc: SearchResult | null;
  onResultClick: (result: SearchResult) => void;
  onOpenPrompt: () => void;
  onClosePrompt: () => void;
  onToggleCollapsed: () => void;
  onToggleExpanded: () => void;
  onOpenMetadata: (result: SearchResult) => void;
  onLanguageChange: (result: SearchResult, newLang: string) => void;
  onRequestHighlight?: (chunkId: string, text: string) => void;
}

export const SearchTabContent: React.FC<SearchTabContentProps> = ({
  filtersExpanded,
  activeFiltersCount,
  onToggleFiltersExpanded,
  onClearFilters,
  facets,
  selectedFilters,
  collapsedFilters,
  expandedFilterLists,
  filterSearchTerms,
  titleSearchResults,
  facetSearchResults,
  onRemoveFilter,
  onToggleFilter,
  onFilterSearchTermChange,
  onToggleFilterListExpansion,
  onFilterValuesChange,
  searchDenseWeight,
  onSearchDenseWeightChange,
  keywordBoostShortQueries,
  onKeywordBoostChange,
  semanticHighlighting,
  onSemanticHighlightingChange,
  minScore,
  maxScore,
  onMinScoreChange,
  autoMinScore,
  onAutoMinScoreToggle,
  rerankEnabled,
  onRerankToggle,
  recencyBoostEnabled,
  onRecencyBoostToggle,
  recencyWeight,
  onRecencyWeightChange,
  recencyScaleDays,
  onRecencyScaleDaysChange,
  minChunkSize,
  onMinChunkSizeChange,
  sectionTypes,
  onSectionTypesChange,
  aiSummaryEnabled,
  aiSummaryCollapsed,
  aiSummaryExpanded,
  aiSummaryLoading,
  aiSummary,
  aiPrompt,
  showPromptModal,
  results,
  loading,
  query,
  selectedDoc,
  onResultClick,
  onOpenPrompt,
  onClosePrompt,
  onToggleCollapsed,
  onToggleExpanded,
  onOpenMetadata,
  onLanguageChange,
  onRequestHighlight,
}) => (
  <div className="main-content">
    <MobileFiltersToggle
      filtersExpanded={filtersExpanded}
      activeFiltersCount={activeFiltersCount}
      onToggle={onToggleFiltersExpanded}
    />

    <div className="content-grid">
      <FiltersPanel
        filtersExpanded={filtersExpanded}
        onClearFilters={onClearFilters}
        facets={facets}
        selectedFilters={selectedFilters}
        collapsedFilters={collapsedFilters}
        expandedFilterLists={expandedFilterLists}
        filterSearchTerms={filterSearchTerms}
        titleSearchResults={titleSearchResults}
        facetSearchResults={facetSearchResults}
        onRemoveFilter={onRemoveFilter}
        onToggleFilter={onToggleFilter}
        onFilterSearchTermChange={onFilterSearchTermChange}
        onToggleFilterListExpansion={onToggleFilterListExpansion}
        onFilterValuesChange={onFilterValuesChange}
        searchDenseWeight={searchDenseWeight}
        onSearchDenseWeightChange={onSearchDenseWeightChange}
        keywordBoostShortQueries={keywordBoostShortQueries}
        onKeywordBoostChange={onKeywordBoostChange}
        semanticHighlighting={semanticHighlighting}
        onSemanticHighlightingChange={onSemanticHighlightingChange}
        minScore={minScore}
        maxScore={maxScore}
        onMinScoreChange={onMinScoreChange}
        autoMinScore={autoMinScore}
        onAutoMinScoreToggle={onAutoMinScoreToggle}
        rerankEnabled={rerankEnabled}
        onRerankToggle={onRerankToggle}
        recencyBoostEnabled={recencyBoostEnabled}
        onRecencyBoostToggle={onRecencyBoostToggle}
        recencyWeight={recencyWeight}
        onRecencyWeightChange={onRecencyWeightChange}
        recencyScaleDays={recencyScaleDays}
        onRecencyScaleDaysChange={onRecencyScaleDaysChange}
        minChunkSize={minChunkSize}
        onMinChunkSizeChange={onMinChunkSizeChange}
        sectionTypes={sectionTypes}
        onSectionTypesChange={onSectionTypesChange}
      />

      <main className="results-section">
        <AiSummaryPanel
          enabled={aiSummaryEnabled}
          aiSummaryCollapsed={aiSummaryCollapsed}
          aiSummaryExpanded={aiSummaryExpanded}
          aiSummaryLoading={aiSummaryLoading}
          aiSummary={aiSummary}
          minScore={minScore}
          results={results}
          aiPrompt={aiPrompt}
          showPromptModal={showPromptModal}
          onToggleCollapsed={onToggleCollapsed}
          onToggleExpanded={onToggleExpanded}
          onResultClick={onResultClick}
          onOpenPrompt={onOpenPrompt}
          onClosePrompt={onClosePrompt}
        />

        <SearchResultsList
          results={results}
          minScore={minScore}
          loading={loading}
          query={query}
          selectedDoc={selectedDoc}
          onResultClick={onResultClick}
          onOpenMetadata={onOpenMetadata}
          onLanguageChange={onLanguageChange}
          onRequestHighlight={onRequestHighlight}
        />
      </main>
    </div>
  </div>
);
