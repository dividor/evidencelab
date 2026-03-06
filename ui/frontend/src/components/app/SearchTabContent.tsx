import React, { useCallback, useMemo, useState, useEffect, useRef } from 'react';
import { Facets, FacetValue, SearchResult, DrilldownNode, SummaryModelConfig } from '../../types/api';
import API_BASE_URL from '../../config';
import { AiSummaryPanel } from '../AiSummaryPanel';
import { FiltersPanel } from '../filters/FiltersPanel';
import { MobileFiltersToggle } from '../MobileFiltersToggle';
import { SearchResultsList } from '../SearchResultsList';
import { useCarouselScroll } from '../../hooks/useCarouselScroll';
import { useRatings } from '../../hooks/useRatings';
import { useAuth } from '../../hooks/useAuth';
import RatingModal from '../ratings/RatingModal';
import { serializeDrilldownTree } from '../../utils/drilldownUtils';

interface SearchTabContentProps {
  filtersExpanded: boolean;
  activeFiltersCount: number;
  onToggleFiltersExpanded: () => void;
  onClearFilters: () => void;
  facets: Facets | null;
  selectedFilters: Record<string, string[]>;
  rangeFilters: Record<string, { min: string; max: string }>;
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
  onRangeChange: (coreField: string, min: string, max: string) => void;
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
  fieldBoostEnabled: boolean;
  onFieldBoostToggle: (value: boolean) => void;
  fieldBoostFields: Record<string, number>;
  onFieldBoostFieldsChange: (fields: Record<string, number>) => void;
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
  onRegenerateAiSummary?: (results: SearchResult[]) => void;
  aiSummaryResults: SearchResult[];
  aiSummaryTranslatedText?: string | null;
  aiSummaryTranslatingLang?: string | null;
  aiSummaryTranslatedLang?: string | null;
  onAiSummaryLanguageChange?: (newLang: string) => void;
  searchId: string;
  aiDrilldownStackDepth?: number;
  aiDrilldownHighlight?: string;
  onAiDrilldown?: (selectedText: string) => void;
  onAiDrilldownBack?: () => void;
  aiDrilldownTree?: DrilldownNode | null;
  aiDrilldownCurrentNodeId?: string | null;
  onAiDrilldownNavigate?: (nodeId: string) => void;
  onFindOutMore?: (keyFacts: string[]) => void;
  findOutMoreLoading?: boolean;
  findOutMoreActiveFact?: string | null;
  requestShowGraph?: boolean;
  dataSource?: string;
  summaryModelConfig?: SummaryModelConfig | null;
  hasSearchRun?: boolean;
  onSaveResearch?: () => void;
  saveResearchLoading?: boolean;
}

const DOT_SIZES = [12, 12, 12, 12, 12];
const DOT_OPACITIES = [1, 0.8, 0.6, 0.4, 0.2];
const TRAIL_GAP = 10; // frames between each trailing dot
const HISTORY_SIZE = TRAIL_GAP * 4 + 1;
const ORBIT_RADIUS = 30;
const ORBIT_PERIOD_MS = 1800;
const ORBIT_COUNT = 3;
const ORBIT_DURATION_MS = ORBIT_PERIOD_MS * ORBIT_COUNT;
const WANDER_MARGIN = 40;

/** Compute edge-repulsion steering to keep the snake away from container walls */
const computeEdgeRepulsion = (
  x: number, y: number, heading: number,
  centerX: number, centerY: number, width: number, height: number,
): number => {
  const toCenterAngle = Math.atan2(centerY - y, centerX - x);
  let pull = 0;
  if (x < WANDER_MARGIN) pull = (WANDER_MARGIN - x) / WANDER_MARGIN;
  if (x > width - WANDER_MARGIN) pull = Math.max(pull, (x - width + WANDER_MARGIN) / WANDER_MARGIN);
  if (y < WANDER_MARGIN) pull = Math.max(pull, (WANDER_MARGIN - y) / WANDER_MARGIN);
  if (y > height - WANDER_MARGIN) pull = Math.max(pull, (y - height + WANDER_MARGIN) / WANDER_MARGIN);
  if (pull <= 0) return heading;
  let diff = toCenterAngle - heading;
  while (diff > Math.PI) diff -= 2 * Math.PI;
  while (diff < -Math.PI) diff += 2 * Math.PI;
  return heading + diff * pull * 0.15;
};

const WanderingSpinner: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const dotsRef = useRef<(HTMLDivElement | null)[]>([]);
  const animFrameRef = useRef<number>(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const bounds = container.getBoundingClientRect();
    const centerX = bounds.width / 2;
    const centerY = bounds.height / 2;

    // Match wander speed to orbit speed so transition is seamless
    const circumference = 2 * Math.PI * ORBIT_RADIUS;
    const framesPerOrbit = ORBIT_PERIOD_MS / 16.67;
    const speed = circumference / framesPerOrbit;

    const history: Array<{ x: number; y: number }> = [];
    let headX = centerX + ORBIT_RADIUS; // start at 0° (right)
    let headY = centerY;
    let wanderAngle = 0;
    let wandering = false;

    // Pre-fill history along the circle so trailing dots appear immediately
    for (let i = 0; i < HISTORY_SIZE; i++) {
      const framesBack = HISTORY_SIZE - 1 - i;
      const pastOrbitAngle = -(framesBack / framesPerOrbit) * 2 * Math.PI;
      history.push({
        x: centerX + ORBIT_RADIUS * Math.cos(pastOrbitAngle),
        y: centerY + ORBIT_RADIUS * Math.sin(pastOrbitAngle),
      });
    }

    const startTime = performance.now();

    const step = (now: number) => {
      if (!containerRef.current) return;
      const elapsed = now - startTime;

      if (!wandering && elapsed < ORBIT_DURATION_MS) {
        const orbitAngle = (elapsed / ORBIT_PERIOD_MS) * 2 * Math.PI;
        headX = centerX + ORBIT_RADIUS * Math.cos(orbitAngle);
        headY = centerY + ORBIT_RADIUS * Math.sin(orbitAngle);
      } else {
        if (!wandering) {
          const orbitAngle = (elapsed / ORBIT_PERIOD_MS) * 2 * Math.PI;
          wanderAngle = orbitAngle + Math.PI / 2;
          wandering = true;
        }
        wanderAngle += (Math.random() - 0.5) * 0.25;
        wanderAngle = computeEdgeRepulsion(headX, headY, wanderAngle, centerX, centerY, bounds.width, bounds.height);
        headX = Math.max(10, Math.min(bounds.width - 10, headX + Math.cos(wanderAngle) * speed));
        headY = Math.max(10, Math.min(bounds.height - 10, headY + Math.sin(wanderAngle) * speed));
      }

      history.push({ x: headX, y: headY });
      if (history.length > HISTORY_SIZE) history.shift();

      // Position each dot from the history — trailing dots read older positions
      for (let i = 0; i < 5; i++) {
        const dot = dotsRef.current[i];
        if (!dot) continue;
        const histIdx = Math.max(0, history.length - 1 - i * TRAIL_GAP);
        const pos = history[histIdx];
        const size = DOT_SIZES[i];
        dot.style.left = `${pos.x - size / 2}px`;
        dot.style.top = `${pos.y - size / 2}px`;
      }

      animFrameRef.current = requestAnimationFrame(step);
    };

    animFrameRef.current = requestAnimationFrame(step);
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  }, []);

  return (
    <div className="search-loading-spinner search-loading-wandering" ref={containerRef}>
      {DOT_SIZES.map((size, i) => (
        <div
          key={i}
          ref={(el) => { dotsRef.current[i] = el; }}
          className="search-loading-snake-dot"
          style={{ width: size, height: size, opacity: DOT_OPACITIES[i] }}
        />
      ))}
    </div>
  );
};

/** Extracted sub-component for the org buttons, document thumbnail carousel, and filter indicator */
const SearchResultFilters: React.FC<{
  uniqueOrgs: Array<{ org: string; count: number }>;
  filteredOrgs: string[];
  onOrgToggle: (org: string) => void;
  filteredDocIds: string[];
  onDocToggle: (docId: string) => void;
  filteredUniqueDocuments: SearchResult[];
  selectedDomain: string;
  hasActiveFilter: boolean;
  filterLabel: string | null;
  thumbnailsRef: React.RefObject<HTMLDivElement | null>;
  canScrollLeft: boolean;
  canScrollRight: boolean;
  scrollThumbnails: (direction: 'left' | 'right') => void;
  onClearAll: () => void;
}> = ({
  uniqueOrgs,
  filteredOrgs,
  onOrgToggle,
  filteredDocIds,
  onDocToggle,
  filteredUniqueDocuments,
  selectedDomain,
  hasActiveFilter,
  filterLabel,
  thumbnailsRef,
  canScrollLeft,
  canScrollRight,
  scrollThumbnails,
  onClearAll,
}) => (
  <div className="search-result-filters">
    <span className="search-result-filters-hint">Click on documents or organizations to refine results</span>
    {uniqueOrgs.length > 0 && (
      <div className="search-result-filters-orgs">
        {uniqueOrgs.map(({ org, count }) => (
          <button
            key={org}
            className={`search-result-filters-org-label ${filteredOrgs.includes(org) ? 'active' : ''}`}
            onClick={() => onOrgToggle(org)}
          >
            {org} ({count})
          </button>
        ))}
      </div>
    )}
    <div className="search-result-filters-thumbnails">
      {canScrollLeft && (
        <button
          className="thumbnail-carousel-arrow thumbnail-carousel-arrow-left"
          onClick={() => scrollThumbnails('left')}
          aria-label="Scroll left"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
        </button>
      )}
      <div className="search-result-filters-thumbnails-container" ref={thumbnailsRef}>
        {filteredUniqueDocuments.map((doc) => {
          const dataSource = doc.data_source || selectedDomain;
          const thumbnailUrl = doc.doc_id
            ? `${API_BASE_URL}/document/${doc.doc_id}/thumbnail?data_source=${dataSource}`
            : null;
          const isSelected = filteredDocIds.includes(doc.doc_id);
          return (
            <div
              key={doc.doc_id}
              className={`search-result-filters-thumbnail ${isSelected ? 'selected' : ''}`}
              onClick={() => onDocToggle(doc.doc_id)}
              title={doc.title || 'Untitled'}
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
      {canScrollRight && (
        <button
          className="thumbnail-carousel-arrow thumbnail-carousel-arrow-right"
          onClick={() => scrollThumbnails('right')}
          aria-label="Scroll right"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
        </button>
      )}
    </div>
    {hasActiveFilter && (
      <div className="search-result-filters-indicator">
        <span className="search-result-filters-indicator-text">
          Showing results from: <strong>{filterLabel}</strong>
        </span>
        <button
          className="search-result-filters-clear"
          onClick={onClearAll}
        >
          × Clear filters
        </button>
      </div>
    )}
  </div>
);

/** Whether AI summary panel should be visible (has content or is loading) */
const isAiSummaryVisible = (
  configEnabled: boolean, results: SearchResult[],
  loading: boolean, summary: string,
): boolean => {
  if (!configEnabled) return false;
  return results.length > 0 || loading || Boolean(summary);
};

export const SearchTabContent: React.FC<SearchTabContentProps> = ({
  filtersExpanded,
  activeFiltersCount,
  onToggleFiltersExpanded,
  onClearFilters,
  facets,
  selectedFilters,
  rangeFilters,
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
  onRangeChange,
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
  fieldBoostEnabled,
  onFieldBoostToggle,
  fieldBoostFields,
  onFieldBoostFieldsChange,
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
  onRegenerateAiSummary,
  aiSummaryResults,
  aiSummaryTranslatedText,
  aiSummaryTranslatingLang,
  aiSummaryTranslatedLang,
  onAiSummaryLanguageChange,
  searchId,
  aiDrilldownStackDepth,
  aiDrilldownHighlight,
  onAiDrilldown,
  onAiDrilldownBack,
  aiDrilldownTree,
  aiDrilldownCurrentNodeId,
  onAiDrilldownNavigate,
  onFindOutMore,
  findOutMoreLoading,
  findOutMoreActiveFact,
  requestShowGraph,
  dataSource,
  summaryModelConfig,
  hasSearchRun,
  onSaveResearch,
  saveResearchLoading,
}) => {
  const [filteredOrgs, setFilteredOrgs] = useState<string[]>(() => {
    const params = new URLSearchParams(window.location.search);
    const orgParam = params.get('carousel_org');
    return orgParam ? orgParam.split(',') : [];
  });
  const [filteredDocIds, setFilteredDocIds] = useState<string[]>(() => {
    const params = new URLSearchParams(window.location.search);
    const docParam = params.get('carousel_doc');
    return docParam ? docParam.split(',') : [];
  });
  const isUserFilterAction = useRef(false);
  const prevSearchIdRef = useRef(searchId);
  const pendingUrlFilterRegen = useRef(filteredOrgs.length > 0 || filteredDocIds.length > 0);

  // Auth state for ratings
  const { isAuthenticated } = useAuth();

  // Ratings for search results (keyed by chunk_id)
  const {
    ratings: searchResultRatings,
    submitRating,
    deleteRating,
  } = useRatings({
    ratingType: 'search_result',
    referenceId: searchId,
    enabled: isAuthenticated && results.length > 0,
  });

  // AI summary rating (keyed by '' since no item_id)
  const {
    ratings: aiSummaryRatings,
    submitRating: submitAiRating,
    deleteRating: deleteAiRating,
  } = useRatings({
    ratingType: 'ai_summary',
    referenceId: searchId,
    enabled: isAuthenticated && !!aiSummary,
  });

  const [aiRatingModalOpen, setAiRatingModalOpen] = useState(false);
  const [aiRatingModalInitialScore, setAiRatingModalInitialScore] = useState(0);
  const aiRating = aiSummaryRatings.get('');

  // Score-filtered results (same threshold used throughout)
  const visibleResults = useMemo(() =>
    results.filter((r) => r.score >= minScore),
    [results, minScore]);

  // Build a compact snapshot of visible results for rating context
  const buildResultsSnapshot = useCallback(() =>
    visibleResults.slice(0, 20).map((r) => ({
      title: r.title,
      doc_id: r.doc_id,
      chunk_id: r.chunk_id,
      page_num: r.page_num || null,
      score: r.score,
      chunk_text: r.text || '',
    })),
    [visibleResults]
  );

  // Wrap submitRating so search-result ratings automatically include the
  // AI summary and results list in context for admin visibility
  const enrichedSubmitRating = useCallback(
    async (params: Parameters<typeof submitRating>[0]) => {
      const enrichedContext = {
        ...params.context,
        ai_summary: aiSummary || '',
        results_snapshot: buildResultsSnapshot(),
        ...(aiDrilldownTree ? { drilldown_tree: serializeDrilldownTree(aiDrilldownTree) } : {}),
      };
      return submitRating({ ...params, context: enrichedContext });
    },
    [submitRating, aiSummary, buildResultsSnapshot, aiDrilldownTree]
  );

  // Handlers for SearchResultFilters sub-component
  const handleOrgToggle = useCallback((org: string) => {
    isUserFilterAction.current = true;
    setFilteredOrgs(prev => prev.includes(org) ? prev.filter(o => o !== org) : [...prev, org]);
  }, []);

  const handleDocToggle = useCallback((docId: string) => {
    isUserFilterAction.current = true;
    setFilteredDocIds(prev => prev.includes(docId) ? prev.filter(d => d !== docId) : [...prev, docId]);
  }, []);

  const handleClearCarouselFilters = useCallback(() => {
    isUserFilterAction.current = true;
    setFilteredOrgs([]);
    setFilteredDocIds([]);
  }, []);

  // Reset carousel filters when a new search is performed.
  // searchId increments in App.tsx each time performSearch is called.
  // On initial mount prevSearchIdRef matches searchId, so no reset occurs
  // — this preserves URL-driven carousel filters on page load.
  useEffect(() => {
    if (prevSearchIdRef.current === searchId) return;
    prevSearchIdRef.current = searchId;
    setFilteredOrgs([]);
    setFilteredDocIds([]);
    const url = new URL(window.location.href);
    if (url.searchParams.has('carousel_org') || url.searchParams.has('carousel_doc')) {
      url.searchParams.delete('carousel_org');
      url.searchParams.delete('carousel_doc');
      window.history.replaceState(null, '', url.toString());
    }
  }, [searchId]);

  // On URL load with carousel filters, regenerate AI summary once results arrive
  useEffect(() => {
    if (!pendingUrlFilterRegen.current || results.length === 0 || !onRegenerateAiSummary) return;
    pendingUrlFilterRegen.current = false;
    const filtered = results
      .filter((r) => filteredOrgs.length === 0 || filteredOrgs.includes(r.organization || 'Unknown'))
      .filter((r) => filteredDocIds.length === 0 || filteredDocIds.includes(r.doc_id));
    onRegenerateAiSummary(filtered);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results]);

  // Regenerate AI summary and sync URL when user changes carousel filters
  useEffect(() => {
    if (!isUserFilterAction.current) return;
    isUserFilterAction.current = false;

    // Sync carousel filter state to URL
    const url = new URL(window.location.href);
    if (filteredOrgs.length > 0) url.searchParams.set('carousel_org', filteredOrgs.join(','));
    else url.searchParams.delete('carousel_org');
    if (filteredDocIds.length > 0) url.searchParams.set('carousel_doc', filteredDocIds.join(','));
    else url.searchParams.delete('carousel_doc');
    window.history.replaceState(null, '', url.toString());

    if (onRegenerateAiSummary) {
      if (filteredOrgs.length > 0 || filteredDocIds.length > 0) {
        const filtered = results
          .filter((r) => filteredOrgs.length === 0 || filteredOrgs.includes(r.organization || 'Unknown'))
          .filter((r) => filteredDocIds.length === 0 || filteredDocIds.includes(r.doc_id));
        onRegenerateAiSummary(filtered);
      } else {
        onRegenerateAiSummary(results);
      }
    }
  }, [filteredOrgs, filteredDocIds, results, onRegenerateAiSummary]);

  // Unique documents from visible results
  const uniqueDocuments = useMemo(() => {
    if (visibleResults.length === 0) return [];
    const getDocKey = (r: SearchResult) => {
      const title = r.title || '';
      const year = r.year || r.metadata?.year || '';
      const org = r.organization || r.metadata?.organization || '';
      return `${title}|${year}|${org}`;
    };
    const seen = new Set<string>();
    const docs: SearchResult[] = [];
    visibleResults.forEach((r) => {
      const key = getDocKey(r);
      if (key !== '||' && !seen.has(key)) {
        seen.add(key);
        docs.push(r);
      }
    });
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

  // Documents filtered by selected orgs
  const filteredUniqueDocuments = useMemo(() =>
    filteredOrgs.length > 0
      ? uniqueDocuments.filter((doc) => filteredOrgs.includes(doc.organization || 'Unknown'))
      : uniqueDocuments,
    [uniqueDocuments, filteredOrgs]);

  const { ref: thumbnailsRef, canScrollLeft, canScrollRight, scroll: scrollThumbnails } =
    useCarouselScroll([filteredUniqueDocuments]);

  // Results filtered by org and document
  const displayedResults = useMemo(() =>
    results
      .filter((r) => filteredOrgs.length === 0 || filteredOrgs.includes(r.organization || 'Unknown'))
      .filter((r) => filteredDocIds.length === 0 || filteredDocIds.includes(r.doc_id)),
    [results, filteredOrgs, filteredDocIds]);

  const filterLabel = useMemo(() => {
    const parts: string[] = [];
    if (filteredOrgs.length > 0) parts.push(filteredOrgs.join(', '));
    if (filteredDocIds.length > 0) {
      const docTitles = filteredDocIds.map(id => {
        const doc = uniqueDocuments.find(d => d.doc_id === id);
        return doc?.title || 'Unknown Document';
      });
      parts.push(docTitles.join(', '));
    }
    return parts.length > 0 ? parts.join(' \u00b7 ') : null;
  }, [filteredOrgs, filteredDocIds, uniqueDocuments]);

  const hasActiveFilter = filteredOrgs.length > 0 || filteredDocIds.length > 0;
  const showFilters = visibleResults.length > 0 && uniqueDocuments.length > 1;

  const contentGridClass = `content-grid ${filtersExpanded ? '' : 'content-grid-no-filters'}`;
  const isInitialLoading = loading && results.length === 0;
  const aiSummaryVisible = isAiSummaryVisible(aiSummaryEnabled, results, aiSummaryLoading, aiSummary);

  const filtersPanelNode = filtersExpanded ? (
    <div className="global-filters-column">
      <FiltersPanel
        filtersExpanded={filtersExpanded}
        onClearFilters={onClearFilters}
        facets={facets}
        selectedFilters={selectedFilters}
        rangeFilters={rangeFilters}
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
        onRangeChange={onRangeChange}
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
        fieldBoostEnabled={fieldBoostEnabled}
        onFieldBoostToggle={onFieldBoostToggle}
        fieldBoostFields={fieldBoostFields}
        onFieldBoostFieldsChange={onFieldBoostFieldsChange}
      />
    </div>
  ) : null;

  if (isInitialLoading) {
    return (
      <div className="main-content">
        <MobileFiltersToggle
          filtersExpanded={filtersExpanded}
          activeFiltersCount={activeFiltersCount}
          onToggle={onToggleFiltersExpanded}
        />
        <div className={`${contentGridClass} search-panel-with-tab`}>
          {filtersPanelNode}
          <main className="results-section">
            <WanderingSpinner />
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="main-content">
      <MobileFiltersToggle
        filtersExpanded={filtersExpanded}
        activeFiltersCount={activeFiltersCount}
        onToggle={onToggleFiltersExpanded}
      />

      <div className={`${contentGridClass} search-panel-with-tab`}>
        {filtersPanelNode}

        <main className="results-section">
          <AiSummaryPanel
            enabled={aiSummaryVisible}
            aiSummaryCollapsed={aiSummaryCollapsed}
            aiSummaryExpanded={aiSummaryExpanded}
            aiSummaryLoading={aiSummaryLoading}
            aiSummary={aiSummary}
            minScore={hasActiveFilter ? 0 : minScore}
            results={aiSummaryResults.length > 0 ? aiSummaryResults : results}
            aiPrompt={aiPrompt}
            showPromptModal={showPromptModal}
            translatedSummary={aiSummaryTranslatedText}
            translatedLang={aiSummaryTranslatedLang}
            isTranslating={!!aiSummaryTranslatingLang}
            translatingLang={aiSummaryTranslatingLang}
            onLanguageChange={onAiSummaryLanguageChange}
            onToggleCollapsed={onToggleCollapsed}
            onToggleExpanded={onToggleExpanded}
            onResultClick={onResultClick}
            onOpenPrompt={onOpenPrompt}
            onClosePrompt={onClosePrompt}
            drilldownStackDepth={aiDrilldownStackDepth}
            drilldownHighlight={aiDrilldownHighlight}
            onDrilldown={onAiDrilldown}
            onDrilldownBack={onAiDrilldownBack}
            drilldownTree={aiDrilldownTree}
            drilldownCurrentNodeId={aiDrilldownCurrentNodeId}
            onDrilldownNavigate={onAiDrilldownNavigate}
            onFindOutMore={onFindOutMore}
            findOutMoreLoading={findOutMoreLoading}
            findOutMoreActiveFact={findOutMoreActiveFact}
            requestShowGraph={requestShowGraph}
            dataSource={dataSource}
            summaryModelConfig={summaryModelConfig}
            isAuthenticated={isAuthenticated}
            onSaveResearch={onSaveResearch}
            saveResearchLoading={saveResearchLoading}
            ratingScore={aiRating?.score || 0}
            onRequestRatingModal={(selectedScore) => {
              setAiRatingModalInitialScore(aiRating?.score || selectedScore);
              setAiRatingModalOpen(true);
            }}
          />
          {aiRatingModalOpen && (
            <RatingModal
              isOpen={aiRatingModalOpen}
              onClose={() => setAiRatingModalOpen(false)}
              title="Rate this AI summary"
              initialScore={aiRatingModalInitialScore}
              initialComment={aiRating?.comment || ''}
              onSubmit={(score, comment) => {
                submitAiRating({
                  ratingType: 'ai_summary',
                  referenceId: searchId,
                  score,
                  comment,
                  context: {
                    query,
                    ai_summary: aiSummary || '',
                    results_snapshot: buildResultsSnapshot(),
                    link: window.location.href,
                    ...(aiDrilldownTree ? { drilldown_tree: serializeDrilldownTree(aiDrilldownTree) } : {}),
                  },
                });
              }}
              onDelete={aiRating?.id ? () => deleteAiRating(aiRating.id) : undefined}
            />
          )}

          {results.length > 0 && <h3 className="search-results-heading">Search Results</h3>}
          {showFilters && (
            <SearchResultFilters
              uniqueOrgs={uniqueOrgs}
              filteredOrgs={filteredOrgs}
              onOrgToggle={handleOrgToggle}
              filteredDocIds={filteredDocIds}
              onDocToggle={handleDocToggle}
              filteredUniqueDocuments={filteredUniqueDocuments}
              selectedDomain={selectedDomain}
              hasActiveFilter={hasActiveFilter}
              filterLabel={filterLabel}
              thumbnailsRef={thumbnailsRef}
              canScrollLeft={canScrollLeft}
              canScrollRight={canScrollRight}
              scrollThumbnails={scrollThumbnails}
              onClearAll={handleClearCarouselFilters}
            />
          )}
          <SearchResultsList
            results={hasActiveFilter ? displayedResults : results}
            minScore={hasActiveFilter ? 0 : minScore}
            loading={loading}
            query={query}
            hasSearchRun={hasSearchRun}
            selectedDoc={selectedDoc}
            onResultClick={onResultClick}
            onOpenMetadata={onOpenMetadata}
            onLanguageChange={onLanguageChange}
            onRequestHighlight={onRequestHighlight}
            searchId={searchId}
            isAuthenticated={isAuthenticated}
            ratingsMap={searchResultRatings}
            onSubmitRating={enrichedSubmitRating}
            onDeleteRating={deleteRating}
          />
        </main>
      </div>
    </div>
  );
};
