import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { SearchResult, DrilldownNode, SummaryModelConfig } from '../types/api';
import API_BASE_URL from '../config';
import { LANGUAGES } from '../constants';
import { RainbowText } from './RainbowText';
import { AiSummaryWithCitations } from './AiSummaryWithCitations';
import { AiSummaryReferences } from './AiSummaryReferences';
import { DigDeeperPopover } from './DigDeeperPopover';
import { DrilldownBreadcrumb } from './DrilldownBreadcrumb';
import { DrilldownGraphView } from './DrilldownGraphView';
import { exportResearchToPdf } from '../utils/exportResearch';
import { patchNodeInTree } from '../utils/drilldownUtils';
import StarRating from './ratings/StarRating';

interface AiSummaryPanelProps {
  enabled: boolean;
  aiSummaryCollapsed: boolean;
  aiSummaryExpanded: boolean;
  aiSummaryLoading: boolean;
  aiSummary: string;
  minScore: number;
  results: SearchResult[];
  aiPrompt: string;
  showPromptModal: boolean;
  translatedSummary?: string | null;
  translatedLang?: string | null;
  isTranslating?: boolean;
  translatingLang?: string | null;
  onLanguageChange?: (newLang: string) => void;
  onToggleCollapsed: () => void;
  onToggleExpanded: () => void;
  onResultClick: (result: SearchResult) => void;
  onOpenPrompt: () => void;
  onClosePrompt: () => void;
  drilldownStackDepth?: number;
  drilldownHighlight?: string;
  onDrilldown?: (selectedText: string) => void;
  onDrilldownBack?: () => void;
  drilldownTree?: DrilldownNode | null;
  drilldownCurrentNodeId?: string | null;
  onDrilldownNavigate?: (nodeId: string) => void;
  onFindOutMore?: (keyFacts: string[]) => void;
  findOutMoreLoading?: boolean;
  findOutMoreActiveFact?: string | null;
  requestShowGraph?: boolean;
  /** Whether user is authenticated */
  isAuthenticated?: boolean;
  /** Current AI summary rating score (0 = unrated) */
  ratingScore?: number;
  /** Callback when user clicks a star to open the rating modal */
  onRequestRatingModal?: (selectedScore: number) => void;
  /** Data source for the global summary API call */
  dataSource?: string;
  /** Summary model config for the global summary API call */
  summaryModelConfig?: SummaryModelConfig | null;
  /** Callback to save current research tree */
  onSaveResearch?: () => void;
  /** Whether save is in progress */
  saveResearchLoading?: boolean;
}

const GeneratingText = () => (
  <span className="generating-text">
    {'Generating AI summary...'.split('').map((char, index) => (
      <span
        key={index}
        className="wave-char"
        style={{ animationDelay: `${index * 0.05}s` }}
      >
        {char === ' ' ? '\u00A0' : char}
      </span>
    ))}
  </span>
);

const AiSummaryLoading = ({ expanded, summary }: { expanded: boolean; summary: string }) => (
  <div className={`ai-summary-content ${expanded ? 'expanded' : ''}`}>
    <p className="ai-summary-text">{summary || <GeneratingText />}</p>
  </div>
);

const AiSummaryBody = ({
  expanded,
  summary,
  filteredResults,
  onResultClick,
  contentRef,
  onDrilldown,
  loading,
  onFindOutMore,
  findOutMoreLoading,
  findOutMoreActiveFact,
}: {
  expanded: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
  contentRef?: React.RefObject<HTMLDivElement | null>;
  onDrilldown?: (text: string) => void;
  loading?: boolean;
  onFindOutMore?: (keyFacts: string[]) => void;
  findOutMoreLoading?: boolean;
  findOutMoreActiveFact?: string | null;
}) => (
  <div
    className={`ai-summary-content ${expanded ? 'expanded' : ''}`}
    ref={contentRef}
    style={{ position: 'relative' }}
  >
    <div className="ai-summary-markdown">
      <AiSummaryWithCitations
        summaryText={summary}
        searchResults={filteredResults}
        onResultClick={onResultClick}
        onFindOutMore={onFindOutMore}
        findOutMoreLoading={findOutMoreLoading}
        findOutMoreActiveFact={findOutMoreActiveFact}
      />
    </div>
    <AiSummaryReferences
      summaryText={summary}
      results={filteredResults}
      onResultClick={onResultClick}
    />
    {onDrilldown && contentRef && !loading && (
      <DigDeeperPopover
        containerRef={contentRef}
        onDrilldown={onDrilldown}
      />
    )}
  </div>
);

const AiSummaryContent = ({
  collapsed,
  expanded,
  loading,
  summary,
  filteredResults,
  onResultClick,
  contentRef,
  onDrilldown,
  onFindOutMore,
  findOutMoreLoading,
  findOutMoreActiveFact,
}: {
  collapsed: boolean;
  expanded: boolean;
  loading: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
  contentRef?: React.RefObject<HTMLDivElement | null>;
  onDrilldown?: (text: string) => void;
  onFindOutMore?: (keyFacts: string[]) => void;
  findOutMoreLoading?: boolean;
  findOutMoreActiveFact?: string | null;
}) => {
  if (collapsed) return null;
  if (loading) return <AiSummaryLoading expanded={expanded} summary={summary} />;
  if (!summary) return null;

  return (
    <AiSummaryBody
      expanded={expanded}
      summary={summary}
      filteredResults={filteredResults}
      onResultClick={onResultClick}
      contentRef={contentRef}
      onDrilldown={onDrilldown}
      loading={loading}
      onFindOutMore={onFindOutMore}
      findOutMoreLoading={findOutMoreLoading}
      findOutMoreActiveFact={findOutMoreActiveFact}
    />
  );
};

const AiSummaryFooter = ({
  collapsed,
  summary,
  loading,
  expanded,
  aiPrompt,
  onToggleExpanded,
  onOpenPrompt,
  isAuthenticated,
  ratingScore,
  onRequestRatingModal,
}: {
  collapsed: boolean;
  summary: string;
  loading: boolean;
  expanded: boolean;
  aiPrompt: string;
  onToggleExpanded: () => void;
  onOpenPrompt: () => void;
  isAuthenticated?: boolean;
  ratingScore?: number;
  onRequestRatingModal?: (selectedScore: number) => void;
}) => {
  if (collapsed || (!summary && !loading)) return null;

  return (
    <div style={{ visibility: !summary ? 'hidden' : 'visible' }}>
      <button className="ai-summary-expand-button" onClick={onToggleExpanded}>
        {expanded ? 'Show less' : 'See more'}
      </button>
      <div className="ai-summary-footer">
        <span className="ai-disclaimer">AI can, and will, gleefully make mistakes</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
          {aiPrompt && (
            <button className="view-prompt-link" onClick={onOpenPrompt}>
              View Prompt
            </button>
          )}
          {isAuthenticated && expanded && onRequestRatingModal && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.78rem', color: 'var(--brand-text-tertiary)' }}>Rate</span>
              <StarRating
                score={ratingScore || 0}
                onRequestModal={onRequestRatingModal}
                size={13}
              />
            </span>
          )}
        </span>
      </div>
    </div>
  );
};

const PromptModal = ({
  show,
  aiPrompt,
  onClose,
}: {
  show: boolean;
  aiPrompt: string;
  onClose: () => void;
}) => {
  if (!show) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>AI Summary Prompt</h3>
          <button className="modal-close-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <pre className="prompt-text">{aiPrompt}</pre>
        </div>
      </div>
    </div>
  );
};

const NetworkIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="12" cy="5" r="3" />
    <circle cx="5" cy="19" r="3" />
    <circle cx="19" cy="19" r="3" />
    <line x1="12" y1="8" x2="5" y2="16" />
    <line x1="12" y1="8" x2="19" y2="16" />
  </svg>
);

const DocumentIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="8" y1="13" x2="16" y2="13" />
    <line x1="8" y1="17" x2="16" y2="17" />
  </svg>
);

const GlobeIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);

const DownloadIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

interface NodeSummary {
  label: string;
  summary: string;
}

const collectNodeSummaries = (node: DrilldownNode): NodeSummary[] => {
  const entries: NodeSummary[] = [];
  if (node.summary) {
    entries.push({ label: node.label, summary: node.summary });
  }
  for (const child of node.children) {
    entries.push(...collectNodeSummaries(child));
  }
  return entries;
};

/** Collect all unique search results from every node in the tree, deduped by chunk_id */
const collectAllResults = (node: DrilldownNode): SearchResult[] => {
  const seen = new Set<string>();
  const all: SearchResult[] = [];
  const walk = (n: DrilldownNode) => {
    for (const r of n.results) {
      if (!seen.has(r.chunk_id)) {
        seen.add(r.chunk_id);
        all.push(r);
      }
    }
    for (const child of n.children) walk(child);
  };
  walk(node);
  return all;
};

const SaveIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
    <polyline points="17 21 17 13 7 13 7 21" />
    <polyline points="7 3 7 8 15 8" />
  </svg>
);

const DrilldownNavRow = ({
  viewMode,
  hasGraph,
  globalSummaryLoading,
  drilldownStackDepth,
  drilldownHighlight,
  onSetViewMode,
  onGenerateGlobalSummary,
  onExportResearch,
  onSaveResearch,
  saveResearchLoading,
  isAuthenticated,
  onDrilldownBack,
}: {
  viewMode: 'summary' | 'tree' | 'global';
  hasGraph: boolean;
  globalSummaryLoading: boolean;
  drilldownStackDepth: number;
  drilldownHighlight?: string;
  onSetViewMode: (mode: 'summary' | 'tree' | 'global') => void;
  onGenerateGlobalSummary: () => void;
  onExportResearch: () => void;
  onSaveResearch?: () => void;
  saveResearchLoading?: boolean;
  isAuthenticated?: boolean;
  onDrilldownBack: () => void;
}) => (
  <div className="ai-drilldown-nav-row">
    {viewMode === 'summary' && hasGraph && (
      <button
        className="drilldown-graph-toggle"
        onClick={() => onSetViewMode('tree')}
        type="button"
      >
        <NetworkIcon />
        Show tree
      </button>
    )}
    {viewMode === 'tree' && (
      <>
        <button
          className="drilldown-graph-toggle"
          onClick={() => onSetViewMode('summary')}
          type="button"
        >
          <DocumentIcon />
          Show summary
        </button>
        {!globalSummaryLoading && (
          <button
            className="drilldown-graph-toggle"
            onClick={onGenerateGlobalSummary}
            type="button"
          >
            <GlobeIcon />
            Generate Global Summary
          </button>
        )}
        {globalSummaryLoading && (
          <span className="global-summary-loading">
            <RainbowText text="Generating global summary..." />
          </span>
        )}
        {isAuthenticated && onSaveResearch && (
          <button
            className="drilldown-graph-toggle"
            onClick={onSaveResearch}
            type="button"
            disabled={saveResearchLoading}
            style={{ marginLeft: 'auto' }}
          >
            <SaveIcon />
            {saveResearchLoading ? 'Saving...' : 'Save your research'}
          </button>
        )}
        <button
          className="drilldown-graph-toggle"
          onClick={onExportResearch}
          type="button"
          style={!(isAuthenticated && onSaveResearch) ? { marginLeft: 'auto' } : undefined}
        >
          <DownloadIcon />
          Export research
        </button>
      </>
    )}
    {viewMode === 'global' && (
      <button
        className="drilldown-graph-toggle"
        onClick={() => onSetViewMode('tree')}
        type="button"
      >
        <NetworkIcon />
        Show tree
      </button>
    )}
    {viewMode === 'summary' && (
      <DrilldownBreadcrumb
        stackDepth={drilldownStackDepth}
        onBack={onDrilldownBack}
        currentHighlight={drilldownHighlight}
      />
    )}
  </div>
);

const LanguageSelector = ({
  selectedLang,
  isTranslating,
  translatingLang,
  onLanguageChange,
}: {
  selectedLang: string;
  isTranslating: boolean;
  translatingLang?: string | null;
  onLanguageChange: (newLang: string) => void;
}) => (
  <div
    className="result-language-selector"
    onClick={(e) => e.stopPropagation()}
    style={{ position: 'relative', display: 'inline-block', marginLeft: 'auto' }}
  >
    {isTranslating && (
      <div
        className="rainbow-overlay translating-dropdown"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'white',
          pointerEvents: 'none',
          fontSize: '0.8rem',
          borderRadius: '4px',
          zIndex: 1
        }}
      >
        <RainbowText text={LANGUAGES[translatingLang || 'en'] || '...'} />
      </div>
    )}
    <select
      value={selectedLang}
      onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
        onLanguageChange(e.target.value)
      }
      style={{
        fontSize: '0.8rem',
        padding: '2px 4px',
        border: 'none',
        borderRadius: '4px',
        backgroundColor: 'transparent',
        color: '#6b7280',
        cursor: 'pointer',
        visibility: isTranslating ? 'hidden' : 'visible'
      }}
    >
      {Object.entries(LANGUAGES).map(([code, name]) => (
        <option key={code} value={code}>
          {name}
        </option>
      ))}
    </select>
  </div>
);

const AiSummaryHeader = ({
  isDrilldown,
  collapsed,
  showGraph,
  aiSummary,
  loading,
  selectedLang,
  isTranslating,
  translatingLang,
  onLanguageChange,
  onToggleCollapsed,
}: {
  isDrilldown: boolean;
  collapsed: boolean;
  showGraph: boolean;
  aiSummary: string;
  loading: boolean;
  selectedLang: string;
  isTranslating: boolean;
  translatingLang?: string | null;
  onLanguageChange?: (newLang: string) => void;
  onToggleCollapsed: () => void;
}) => (
  <div className="ai-summary-header">
    <h3 className="ai-summary-title">
      {isDrilldown ? 'AI Summary Tree' : 'AI Summary'}
    </h3>
    {aiSummary && !loading && !showGraph && onLanguageChange && (
      <LanguageSelector
        selectedLang={selectedLang}
        isTranslating={isTranslating}
        translatingLang={translatingLang}
        onLanguageChange={onLanguageChange}
      />
    )}
    <button className="ai-summary-toggle" type="button" onClick={onToggleCollapsed}>
      {collapsed ? 'Expand' : 'Collapse'}
    </button>
  </div>
);

export const AiSummaryPanel = ({
  enabled,
  aiSummaryCollapsed,
  aiSummaryExpanded,
  aiSummaryLoading,
  aiSummary,
  minScore,
  results,
  aiPrompt,
  showPromptModal,
  translatedSummary,
  translatedLang,
  isTranslating,
  translatingLang,
  onLanguageChange,
  onToggleCollapsed,
  onToggleExpanded,
  onResultClick,
  onOpenPrompt,
  onClosePrompt,
  drilldownStackDepth,
  drilldownHighlight,
  onDrilldown,
  onDrilldownBack,
  drilldownTree,
  drilldownCurrentNodeId,
  onDrilldownNavigate,
  onFindOutMore,
  findOutMoreLoading,
  findOutMoreActiveFact,
  requestShowGraph,
  isAuthenticated,
  ratingScore = 0,
  onRequestRatingModal,
  dataSource,
  summaryModelConfig,
  onSaveResearch,
  saveResearchLoading,
}: AiSummaryPanelProps) => {
  const summaryContentRef = useRef<HTMLDivElement>(null);
  // viewMode: 'summary' = node summary, 'tree' = graph, 'global' = global summary
  const [viewMode, setViewMode] = useState<'summary' | 'tree' | 'global'>('summary');
  const [globalSummary, setGlobalSummary] = useState('');
  const [globalSummaryResults, setGlobalSummaryResults] = useState<SearchResult[]>([]);
  const [globalSummaryLoading, setGlobalSummaryLoading] = useState(false);

  useEffect(() => {
    if (requestShowGraph) setViewMode('tree');
  }, [requestShowGraph]);

  // Reset global summary when tree changes
  useEffect(() => {
    setGlobalSummary('');
    setGlobalSummaryResults([]);
  }, [drilldownTree]);

  const handleGenerateGlobalSummary = useCallback(async () => {
    if (!drilldownTree || globalSummaryLoading) return;
    const summaries = collectNodeSummaries(drilldownTree);
    if (summaries.length === 0) return;

    const allResults = collectAllResults(drilldownTree);
    if (allResults.length === 0) return;

    setGlobalSummaryLoading(true);
    try {
      const rootLabel = drilldownTree.label || 'research';
      const summaryContext = summaries
        .map((s) => `- ${s.label}: ${s.summary}`)
        .join('\n');
      const q = `Synthesise a comprehensive global summary from the following research topics, in the context of: "${rootLabel}". Use the search results below to cite sources.\n\nResearch summaries so far:\n${summaryContext}`;
      const resp = await axios.post<{ summary: string }>(
        `${API_BASE_URL}/ai-summary?data_source=${dataSource || 'default'}`,
        {
          query: q,
          results: allResults.map((r) => ({
            chunk_id: r.chunk_id,
            doc_id: r.doc_id,
            text: r.text,
            title: r.title,
            page_num: r.page_num,
            headings: r.headings || [],
            score: r.score,
            organization: r.organization,
            year: r.year,
          })),
          max_results: allResults.length,
          ...(summaryModelConfig ? { summary_model_config: summaryModelConfig } : {}),
        }
      );
      setGlobalSummary(resp.data.summary);
      setGlobalSummaryResults(allResults);
      setViewMode('global');
    } catch (err) {
      console.error('Failed to generate global summary:', err);
    } finally {
      setGlobalSummaryLoading(false);
    }
  }, [drilldownTree, globalSummaryLoading, dataSource, summaryModelConfig]);

  if (!enabled) return null;

  const filteredResults = results.filter((result) => result.score >= minScore);
  const displaySummary = translatedSummary || aiSummary;
  const selectedLang = translatedLang || 'en';
  const isDrilldown = (drilldownStackDepth || 0) > 0;
  const hasGraph = drilldownTree && drilldownTree.children.length > 0;
  const showGraphView = viewMode === 'tree' && hasGraph && onDrilldownNavigate;
  const showGlobalView = viewMode === 'global' && globalSummary;

  return (
    <>
      <div className={`ai-summary-box ${aiSummaryCollapsed ? 'collapsed' : ''}`}>
        <AiSummaryHeader
          isDrilldown={isDrilldown}
          collapsed={aiSummaryCollapsed}
          showGraph={viewMode !== 'summary'}
          aiSummary={aiSummary}
          loading={aiSummaryLoading}
          selectedLang={selectedLang}
          isTranslating={!!isTranslating}
          translatingLang={translatingLang}
          onLanguageChange={onLanguageChange}
          onToggleCollapsed={onToggleCollapsed}
        />
        {!aiSummaryCollapsed && aiSummary && !aiSummaryLoading && viewMode === 'summary' && (
          <p className="ai-summary-hint">You can highlight text below or click the &apos;Find out more&apos; button to research sub-topics.</p>
        )}
        {!aiSummaryCollapsed && onDrilldownBack && (
          <DrilldownNavRow
            viewMode={viewMode}
            hasGraph={!!hasGraph}
            globalSummaryLoading={globalSummaryLoading}
            drilldownStackDepth={drilldownStackDepth || 0}
            drilldownHighlight={drilldownHighlight}
            onSetViewMode={setViewMode}
            onGenerateGlobalSummary={handleGenerateGlobalSummary}
            onExportResearch={() => {
              if (drilldownTree) {
                // Patch the currently-viewed node's live state into the tree before exporting
                const currentId = drilldownCurrentNodeId || drilldownTree.id;
                const patchedTree = patchNodeInTree(drilldownTree, currentId, aiSummary, results);
                exportResearchToPdf(
                  patchedTree,
                  globalSummary || undefined,
                  globalSummaryResults
                );
              }
            }}
            onSaveResearch={onSaveResearch}
            saveResearchLoading={saveResearchLoading}
            isAuthenticated={isAuthenticated}
            onDrilldownBack={onDrilldownBack}
          />
        )}
        {showGraphView ? (
          <>
            <p className="ai-summary-hint" style={{ fontStyle: 'italic' }}>Click on nodes below to see their results and summaries.</p>
            <DrilldownGraphView
              tree={drilldownTree!}
              activeNodeId={drilldownCurrentNodeId || 'root'}
              onNodeClick={(nodeId) => {
                onDrilldownNavigate!(nodeId);
                setViewMode('summary');
              }}
            />
          </>
        ) : showGlobalView ? (
          <div className="ai-summary-content expanded global-summary-content">
            <div className="ai-summary-markdown">
              <AiSummaryWithCitations
                summaryText={globalSummary}
                searchResults={globalSummaryResults}
                onResultClick={onResultClick}
              />
            </div>
            <AiSummaryReferences
              summaryText={globalSummary}
              results={globalSummaryResults}
              onResultClick={onResultClick}
            />
          </div>
        ) : (
          <>
            <AiSummaryContent
              collapsed={aiSummaryCollapsed}
              expanded={aiSummaryExpanded}
              loading={aiSummaryLoading}
              summary={displaySummary}
              filteredResults={filteredResults}
              onResultClick={onResultClick}
              contentRef={summaryContentRef}
              onDrilldown={onDrilldown}
              onFindOutMore={onFindOutMore}
              findOutMoreLoading={findOutMoreLoading}
              findOutMoreActiveFact={findOutMoreActiveFact}
            />
            <AiSummaryFooter
              collapsed={aiSummaryCollapsed}
              summary={displaySummary}
              loading={aiSummaryLoading}
              expanded={aiSummaryExpanded}
              aiPrompt={aiPrompt}
              onToggleExpanded={onToggleExpanded}
              onOpenPrompt={onOpenPrompt}
              isAuthenticated={isAuthenticated}
              ratingScore={ratingScore}
              onRequestRatingModal={onRequestRatingModal}
            />
          </>
        )}
      </div>

      <PromptModal show={showPromptModal} aiPrompt={aiPrompt} onClose={onClosePrompt} />
    </>
  );
};
