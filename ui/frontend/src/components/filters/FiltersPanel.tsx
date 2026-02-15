import React from 'react';
import { Facets, FacetValue } from '../../types/api';
import { FilterSections, SelectedFiltersDisplay } from './FilterComponents';
import { SearchSettingsPanel } from './SearchSettingsPanel';

interface FiltersPanelProps {
  filtersExpanded: boolean;
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
  deduplicateEnabled: boolean;
  onDeduplicateToggle: (value: boolean) => void;
}

export const FiltersPanel: React.FC<FiltersPanelProps> = ({
  filtersExpanded,
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
  deduplicateEnabled,
  onDeduplicateToggle,
}) => (
  <aside className={`filters-section ${filtersExpanded ? 'filters-section-expanded' : ''}`}>
    <div className="filters-card">
      <div className="filters-header">
        <h2 className="section-heading">Filters</h2>
        <button onClick={onClearFilters} className="clear-filters-link">
          Clear filters
        </button>
      </div>
      {facets && (
        <>
          <SelectedFiltersDisplay
            facets={facets}
            selectedFilters={selectedFilters}
            onRemove={onRemoveFilter}
          />

          <FilterSections
            facets={facets}
            selectedFilters={selectedFilters}
            collapsedFilters={collapsedFilters}
            expandedFilterLists={expandedFilterLists}
            filterSearchTerms={filterSearchTerms}
            titleSearchResults={titleSearchResults}
            facetSearchResults={facetSearchResults}
            onToggleFilter={onToggleFilter}
            onSearchTermChange={onFilterSearchTermChange}
            onToggleFilterListExpansion={onToggleFilterListExpansion}
            onFilterValuesChange={onFilterValuesChange}
          />

          <SearchSettingsPanel
            collapsedFilters={collapsedFilters}
            onToggleFilter={onToggleFilter}
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
            deduplicateEnabled={deduplicateEnabled}
            onDeduplicateToggle={onDeduplicateToggle}
          />
        </>
      )}
    </div>
  </aside>
);
