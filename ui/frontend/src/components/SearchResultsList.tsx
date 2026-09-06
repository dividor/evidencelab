import React, { useEffect, useState } from 'react';
import { SearchResult } from '../types/api';
import SearchResultCard from './SearchResultCard';
import { DocumentResultGroup } from './DocumentResultGroup';
import { groupResultsByDocument } from '../utils/resultGrouping';
import API_BASE_URL from '../config';
import type { Rating } from '../hooks/useRatings';

interface SearchResultsListProps {
  results: SearchResult[];
  minScore: number;
  /** Show one collapsed row per document instead of a flat list of excerpts. */
  groupByDocument?: boolean;
  /** Documents whose rows start expanded (for example, one picked in the carousel). */
  defaultExpandedDocIds?: string[];
  /** Data source used for row thumbnails when a result does not carry its own. */
  thumbnailDataSource?: string;
  loading: boolean;
  query: string;
  hasSearchRun?: boolean;
  selectedDoc: SearchResult | null;
  onResultClick: (result: SearchResult) => void;
  onOpenMetadata: (result: SearchResult) => void;
  onLanguageChange: (result: SearchResult, newLang: string) => void;
  onRequestHighlight?: (chunkId: string, text: string) => void;
  hidePageNumber?: boolean;
  /** UUID search ID for ratings */
  searchId?: string;
  /** Whether user is authenticated */
  isAuthenticated?: boolean;
  /** Map of item_id → Rating for this search */
  ratingsMap?: Map<string, Rating>;
  /** Submit a rating */
  onSubmitRating?: (params: {
    ratingType: string;
    referenceId: string;
    itemId?: string;
    score: number;
    comment?: string;
    context?: Record<string, any>;
  }) => Promise<any>;
  /** Delete a rating */
  onDeleteRating?: (ratingId: string) => Promise<void>;
}

export const SearchResultsList = ({
  results,
  minScore,
  groupByDocument = false,
  defaultExpandedDocIds,
  thumbnailDataSource,
  loading,
  query,
  hasSearchRun,
  selectedDoc,
  onResultClick,
  onOpenMetadata,
  onLanguageChange,
  onRequestHighlight,
  hidePageNumber,
  searchId,
  isAuthenticated,
  ratingsMap,
  onSubmitRating,
  onDeleteRating,
}: SearchResultsListProps) => {
  const visibleResults = results.filter((result) => result.score >= minScore);

  const renderCard = (result: SearchResult) => {
    const rating = ratingsMap?.get(result.chunk_id);
    return (
      <SearchResultCard
        key={result.chunk_id}
        result={result}
        query={query}
        isSelected={selectedDoc?.chunk_id === result.chunk_id}
        onClick={onResultClick}
        onOpenMetadata={onOpenMetadata}
        onLanguageChange={onLanguageChange}
        onRequestHighlight={onRequestHighlight}
        hidePageNumber={hidePageNumber}
        searchId={searchId}
        isAuthenticated={isAuthenticated}
        onSubmitRating={onSubmitRating}
        existingRatingScore={rating?.score || 0}
        existingRatingComment={rating?.comment || ''}
        existingRatingId={rating?.id}
        onDeleteRating={onDeleteRating}
      />
    );
  };

  return (
    <div className="results-list">
      {results.length === 0 && !loading && !hasSearchRun && (
        <div className="no-results-message welcome-message">
          <h3>Ready to explore</h3>
          <p>Enter a search query above to start discovering insights across your documents.</p>
        </div>
      )}
      {results.length === 0 && !loading && hasSearchRun && (
        <div className="no-results-message">
          <h3>No results found</h3>
          <p>Try adjusting your search terms or filters.</p>
        </div>
      )}
      {groupByDocument ? (
        <GroupedResults
          results={visibleResults}
          defaultExpandedDocIds={defaultExpandedDocIds}
          thumbnailDataSource={thumbnailDataSource}
          renderCard={renderCard}
        />
      ) : (
        visibleResults.map(renderCard)
      )}
    </div>
  );
};

/**
 * Grouped view: one collapsible row per document, collapsed by default.
 * Rows a user has toggled are remembered until the result set changes.
 */
const thumbnailUrlFor = (result: SearchResult, fallbackDataSource?: string): string | null => {
  const dataSource = result.data_source || fallbackDataSource;
  if (!result.doc_id || !dataSource) return null;
  return `${API_BASE_URL}/document/${result.doc_id}/thumbnail?data_source=${dataSource}`;
};

const GroupedResults = ({
  results,
  defaultExpandedDocIds,
  thumbnailDataSource,
  renderCard,
}: {
  results: SearchResult[];
  defaultExpandedDocIds?: string[];
  thumbnailDataSource?: string;
  renderCard: (result: SearchResult) => React.ReactNode;
}) => {
  const groups = groupResultsByDocument(results);
  // Explicit user choices per document; anything else follows the default.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setToggled({});
  }, [results]);

  const isExpanded = (docId: string) =>
    toggled[docId] ?? (defaultExpandedDocIds?.includes(docId) ?? false);
  const setAll = (expanded: boolean) =>
    setToggled(Object.fromEntries(groups.map((group) => [group.docId, expanded])));

  if (groups.length === 0) return null;
  return (
    <>
      <div className="results-group-actions">
        <span className="results-group-summary">
          {results.length} {results.length === 1 ? 'excerpt' : 'excerpts'} in {groups.length}{' '}
          {groups.length === 1 ? 'document' : 'documents'}
        </span>
        <button type="button" onClick={() => setAll(true)}>Expand all</button>
        <button type="button" onClick={() => setAll(false)}>Collapse all</button>
      </div>
      {groups.map((group) => (
        <DocumentResultGroup
          key={group.docId}
          results={group.results}
          thumbnailUrl={thumbnailUrlFor(group.results[0], thumbnailDataSource)}
          expanded={isExpanded(group.docId)}
          onToggle={() => setToggled((prev) => ({ ...prev, [group.docId]: !isExpanded(group.docId) }))}
          renderResult={renderCard}
        />
      ))}
    </>
  );
};
