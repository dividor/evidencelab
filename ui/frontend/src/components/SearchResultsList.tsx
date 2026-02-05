import React from 'react';
import { SearchResult } from '../types/api';
import SearchResultCard from './SearchResultCard';

interface SearchResultsListProps {
  results: SearchResult[];
  minScore: number;
  loading: boolean;
  query: string;
  selectedDoc: SearchResult | null;
  onResultClick: (result: SearchResult) => void;
  onOpenMetadata: (result: SearchResult) => void;
  onLanguageChange: (result: SearchResult, newLang: string) => void;
  onRequestHighlight?: (chunkId: string, text: string) => void;
}

export const SearchResultsList = ({
  results,
  minScore,
  loading,
  query,
  selectedDoc,
  onResultClick,
  onOpenMetadata,
  onLanguageChange,
  onRequestHighlight,
}: SearchResultsListProps) => {
  const visibleResults = results.filter((result) => result.score >= minScore);

  return (
    <div className="results-list">
      {results.length === 0 && !loading && (
        <div className="no-results-message">
          <h3>No results found</h3>
          <p>Try adjusting your search terms or filters.</p>
        </div>
      )}
      {visibleResults.map((result) => (
        <SearchResultCard
          key={result.chunk_id}
          result={result}
          query={query}
          isSelected={selectedDoc?.chunk_id === result.chunk_id}
          onClick={onResultClick}
          onOpenMetadata={onOpenMetadata}
          onLanguageChange={onLanguageChange}
          onRequestHighlight={onRequestHighlight}
        />
      ))}
    </div>
  );
};
