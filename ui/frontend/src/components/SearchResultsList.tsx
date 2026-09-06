import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SearchResult } from '../types/api';
import SearchResultCard from './SearchResultCard';
import { DocumentResultGroup } from './DocumentResultGroup';
import { groupResultsByDocument, sortDocumentGroups } from '../utils/resultGrouping';
import type { GroupSortBy } from '../utils/resultGrouping';
import API_BASE_URL from '../config';
import type { Rating } from '../hooks/useRatings';

/** Expand or collapse every document row. A fresh id re-applies the same choice. */
export interface ExpansionCommand {
  expand: boolean;
  id: number;
}

interface SearchResultsListProps {
  results: SearchResult[];
  minScore: number;
  /** Show one collapsed row per document instead of a flat list of excerpts. */
  groupByDocument?: boolean;
  /** Documents whose rows start expanded (for example, one picked in the carousel). */
  defaultExpandedDocIds?: string[];
  /** Data source used for row thumbnails when a result does not carry its own. */
  thumbnailDataSource?: string;
  /** Order of the document rows in grouped mode. */
  groupSortBy?: GroupSortBy;
  /** Expand or collapse every row; a new id applies the command again. */
  expansionCommand?: ExpansionCommand;
  /** Reports whether every row is currently expanded (drives the header button). */
  onAllExpandedChange?: (allExpanded: boolean) => void;
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
  groupSortBy = 'relevance',
  expansionCommand,
  onAllExpandedChange,
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
  const visibleResults = useMemo(
    () => results.filter((result) => result.score >= minScore),
    [results, minScore],
  );

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
          sortBy={groupSortBy}
          expansionCommand={expansionCommand}
          onAllExpandedChange={onAllExpandedChange}
          onRequestHighlight={onRequestHighlight}
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
  sortBy,
  expansionCommand,
  onAllExpandedChange,
  onRequestHighlight,
  renderCard,
}: {
  results: SearchResult[];
  defaultExpandedDocIds?: string[];
  thumbnailDataSource?: string;
  sortBy: GroupSortBy;
  expansionCommand?: ExpansionCommand;
  onAllExpandedChange?: (allExpanded: boolean) => void;
  onRequestHighlight?: (chunkId: string, text: string) => void;
  renderCard: (result: SearchResult) => React.ReactNode;
}) => {
  const groups = useMemo(
    () => sortDocumentGroups(groupResultsByDocument(results), sortBy),
    [results, sortBy],
  );
  // Explicit user choices per document; anything else follows the default.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  // Collapse everything only when the set of documents changes (a new search
  // or filter), not on every parent re-render: the AI summary streams tokens
  // while the user is reading, and each token re-renders this list.
  const documentKey = groups.map((group) => group.docId).sort().join('|');
  // Excerpts whose highlights this list has already asked for (see below).
  const highlightRequested = useRef(new Set<string>());
  useEffect(() => {
    setToggled({});
    highlightRequested.current = new Set();
  }, [documentKey]);

  const defaultExpanded = useCallback(
    (docId: string) => defaultExpandedDocIds?.includes(docId) ?? false,
    [defaultExpandedDocIds],
  );
  const isExpanded = useCallback(
    (docId: string) => toggled[docId] ?? defaultExpanded(docId),
    [toggled, defaultExpanded],
  );
  const toggle = (docId: string) =>
    setToggled((prev) => ({ ...prev, [docId]: !(prev[docId] ?? defaultExpanded(docId)) }));

  // Expanding a row is an explicit action, so ask for its excerpts' semantic
  // highlights at once instead of waiting for each card to scroll into view.
  const expandedGroups = useMemo(() => groups.filter((group) => isExpanded(group.docId)), [groups, isExpanded]);
  useEffect(() => {
    if (!onRequestHighlight) return;
    expandedGroups.forEach((group) =>
      group.results.forEach((result) => {
        if (result.highlightedText || highlightRequested.current.has(result.chunk_id)) return;
        highlightRequested.current.add(result.chunk_id);
        onRequestHighlight(result.chunk_id, result.text);
      }),
    );
  }, [expandedGroups, onRequestHighlight]);
  // Expand all / collapse all from the results header: each command id is
  // applied once, to the rows present at that moment.
  const appliedCommandId = useRef(0);
  useEffect(() => {
    if (!expansionCommand || expansionCommand.id === appliedCommandId.current) return;
    appliedCommandId.current = expansionCommand.id;
    setToggled(Object.fromEntries(groups.map((group) => [group.docId, expansionCommand.expand])));
  }, [expansionCommand, groups]);
  const allExpanded = groups.length > 0 && groups.every((group) => isExpanded(group.docId));
  useEffect(() => {
    onAllExpandedChange?.(allExpanded);
  }, [allExpanded, onAllExpandedChange]);

  if (groups.length === 0) return null;
  return (
    <>
      <div className="results-group-actions">
        <span className="results-group-summary">
          {results.length} {results.length === 1 ? 'excerpt' : 'excerpts'} in {groups.length}{' '}
          {groups.length === 1 ? 'document' : 'documents'}
        </span>
      </div>
      {groups.map((group) => (
        <DocumentResultGroup
          key={group.docId}
          results={group.results}
          thumbnailUrl={thumbnailUrlFor(group.results[0], thumbnailDataSource)}
          expanded={isExpanded(group.docId)}
          onToggle={() => toggle(group.docId)}
          renderResult={renderCard}
        />
      ))}
    </>
  );
};
