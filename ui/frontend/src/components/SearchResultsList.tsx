import React from 'react';
import { SearchResult } from '../types/api';
import SearchResultCard from './SearchResultCard';
import type { Rating } from '../hooks/useRatings';

interface SearchResultsListProps {
  results: SearchResult[];
  minScore: number;
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
      {visibleResults.map((result) => {
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
      })}
    </div>
  );
};
