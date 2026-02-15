import React, { useMemo, useState, useEffect } from 'react';
import { Facets, FacetValue, SearchResult } from '../../types/api';
import API_BASE_URL from '../../config';
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
  deduplicateEnabled: boolean;
  onDeduplicateToggle: (value: boolean) => void;
  aiSummaryEnabled: boolean;
  aiSummaryCollapsed: boolean;
  aiSummaryExpanded: boolean;
  aiSummaryLoading: boolean;
  aiSummary: string;
  aiPrompt: string;
  showPromptModal: boolean;
  selectedDomain: string;
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
  deduplicateEnabled,
  onDeduplicateToggle,
  aiSummaryEnabled,
  aiSummaryCollapsed,
  aiSummaryExpanded,
  aiSummaryLoading,
  aiSummary,
  aiPrompt,
  showPromptModal,
  selectedDomain,
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
}) => {
  const [filteredOrg, setFilteredOrg] = useState<string | null>(null);
  const [filteredDocId, setFilteredDocId] = useState<string | null>(null);

  // Score-filtered results (same threshold used throughout)
  const visibleResults = useMemo(() =>
    results.filter((r) => r.score >= minScore),
    [results, minScore]);

  // Stable fingerprint of which chunks are present – changes only on a new
  // search, NOT when semantic-highlighting mutates individual result objects.
  const resultsFingerprint = useMemo(
    () => results.map((r) => r.chunk_id).join(','),
    [results]
  );

  // Reset filters when the actual result set changes (new search)
  useEffect(() => {
    setFilteredOrg(null);
    setFilteredDocId(null);
  }, [resultsFingerprint]);

  // Unique documents from visible results
  const uniqueDocuments = useMemo(() => {
    if (visibleResults.length === 0) return [];
    const getDocKey = (r: SearchResult) => {
      const title = r.title || '';
      const year = r.year || r.metadata?.year || '';
      const org = r.organization || r.metadata?.organization || '';
      return `${title}|${year}|${org}`;
    };
    const docCounts = new Map<string, number>();
    visibleResults.forEach((r) => {
      const key = getDocKey(r);
      if (key !== '||') docCounts.set(key, (docCounts.get(key) || 0) + 1);
    });
    const seen = new Set<string>();
    const docs: SearchResult[] = [];
    visibleResults.forEach((r) => {
      const key = getDocKey(r);
      if (key !== '||' && !seen.has(key)) {
        seen.add(key);
        docs.push(r);
      }
    });
    docs.sort((a, b) => (docCounts.get(getDocKey(b)) || 0) - (docCounts.get(getDocKey(a)) || 0));
    return docs;
  }, [visibleResults]);

  // Unique orgs with counts
  const uniqueOrgs = useMemo(() => {
    const orgCounts = new Map<string, number>();
    uniqueDocuments.forEach((doc) => {
      const org = doc.organization || 'Unknown';
      orgCounts.set(org, (orgCounts.get(org) || 0) + 1);
    });
    return Array.from(orgCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([org, count]) => ({ org, count }));
  }, [uniqueDocuments]);

  // Documents filtered by selected org
  const filteredUniqueDocuments = useMemo(() =>
    filteredOrg
      ? uniqueDocuments.filter((doc) => (doc.organization || 'Unknown') === filteredOrg)
      : uniqueDocuments,
    [uniqueDocuments, filteredOrg]);

  // Results filtered by org and document
  const displayedResults = useMemo(() =>
    results
      .filter((r) => !filteredOrg || (r.organization || 'Unknown') === filteredOrg)
      .filter((r) => !filteredDocId || r.doc_id === filteredDocId),
    [results, filteredOrg, filteredDocId]);

  const filteredDocTitle = useMemo(() => {
    if (!filteredDocId) return null;
    const doc = uniqueDocuments.find(d => d.doc_id === filteredDocId);
    return doc?.title || 'Unknown Document';
  }, [filteredDocId, uniqueDocuments]);

  const filterLabel = useMemo(() => {
    if (filteredDocId) return filteredDocTitle;
    if (filteredOrg) return filteredOrg;
    return null;
  }, [filteredDocId, filteredOrg, filteredDocTitle]);

  const hasActiveFilter = filteredOrg !== null || filteredDocId !== null;
  const showFilters = visibleResults.length > 0 && uniqueDocuments.length > 1;

  return (
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
          deduplicateEnabled={deduplicateEnabled}
          onDeduplicateToggle={onDeduplicateToggle}
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

          {showFilters && (
            <div className="search-result-filters">
              {uniqueOrgs.length > 1 && (
                <div className="search-result-filters-orgs">
                  {uniqueOrgs.map(({ org, count }) => (
                    <button
                      key={org}
                      className={`search-result-filters-org-label ${filteredOrg === org ? 'active' : ''}`}
                      onClick={() => {
                        setFilteredOrg(filteredOrg === org ? null : org);
                        setFilteredDocId(null);
                      }}
                    >
                      {org} ({count})
                    </button>
                  ))}
                </div>
              )}
              <div className="search-result-filters-thumbnails">
                <div className="search-result-filters-thumbnails-container">
                  {filteredUniqueDocuments.map((doc) => {
                    const dataSource = doc.data_source || selectedDomain;
                    const thumbnailUrl = doc.doc_id
                      ? `${API_BASE_URL}/document/${doc.doc_id}/thumbnail?data_source=${dataSource}`
                      : null;
                    const isSelected = filteredDocId === doc.doc_id;
                    return (
                      <div
                        key={doc.doc_id}
                        className={`search-result-filters-thumbnail ${isSelected ? 'selected' : ''}`}
                        onClick={() => setFilteredDocId(isSelected ? null : doc.doc_id)}
                        title="Click on a document to filter results below"
                      >
                        <div className="search-result-filters-thumbnail-image">
                          {thumbnailUrl ? (
                            <img
                              src={thumbnailUrl}
                              alt={doc.title || 'Document thumbnail'}
                              className="search-result-filters-thumbnail-img"
                              onError={(e) => {
                                (e.target as HTMLImageElement).style.display = 'none';
                              }}
                            />
                          ) : (
                            <div className="search-result-filters-thumbnail-placeholder">
                              No thumbnail
                            </div>
                          )}
                        </div>
                        <div className="search-result-filters-thumbnail-info">
                          <div className="search-result-filters-thumbnail-title">
                            {doc.title || 'Untitled'}
                          </div>
                          {(doc.organization || doc.year) && (
                            <div className="search-result-filters-thumbnail-source">
                              {doc.organization}
                              {doc.organization && doc.year && ' \u2022 '}
                              {doc.year}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              {hasActiveFilter && (
                <div className="search-result-filters-indicator">
                  <span className="search-result-filters-indicator-text">
                    Showing results from: <strong>{filterLabel}</strong>
                  </span>
                  <button
                    className="search-result-filters-clear"
                    onClick={() => { setFilteredOrg(null); setFilteredDocId(null); }}
                  >
                    × Clear filter
                  </button>
                </div>
              )}
            </div>
          )}

          <SearchResultsList
            results={hasActiveFilter ? displayedResults : results}
            minScore={hasActiveFilter ? 0 : minScore}
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
};
