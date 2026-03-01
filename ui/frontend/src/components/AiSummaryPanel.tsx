import React, { useEffect, useRef, useState } from 'react';
import { SearchResult, DrilldownNode } from '../types/api';
import { LANGUAGES } from '../constants';
import { RainbowText } from './RainbowText';
import { AiSummaryWithCitations } from './AiSummaryWithCitations';
import { AiSummaryReferences } from './AiSummaryReferences';
import { DigDeeperPopover } from './DigDeeperPopover';
import { DrilldownBreadcrumb } from './DrilldownBreadcrumb';
import { DrilldownGraphView } from './DrilldownGraphView';

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
}: {
  collapsed: boolean;
  summary: string;
  loading: boolean;
  expanded: boolean;
  aiPrompt: string;
  onToggleExpanded: () => void;
  onOpenPrompt: () => void;
}) => {
  if (collapsed || (!summary && !loading)) return null;

  return (
    <div style={{ visibility: !summary ? 'hidden' : 'visible' }}>
      <button className="ai-summary-expand-button" onClick={onToggleExpanded}>
        {expanded ? 'Show less' : 'See more'}
      </button>
      <div className="ai-summary-footer">
        <span className="ai-disclaimer">AI can, and will, gleefully make mistakes</span>
        {aiPrompt && (
          <button className="view-prompt-link" onClick={onOpenPrompt}>
            View Prompt
          </button>
        )}
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

const GraphToggleButton = ({
  showGraph,
  onToggle,
}: {
  showGraph: boolean;
  onToggle: () => void;
}) => (
  <button
    className={`drilldown-graph-toggle ${showGraph ? 'active' : ''}`}
    onClick={(e) => {
      e.stopPropagation();
      onToggle();
    }}
    type="button"
  >
    {showGraph ? <DocumentIcon /> : <NetworkIcon />}
    {showGraph ? 'Show summary' : 'Show tree'}
  </button>
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
}: AiSummaryPanelProps) => {
  const summaryContentRef = useRef<HTMLDivElement>(null);
  const [showGraph, setShowGraph] = useState(false);

  useEffect(() => {
    if (requestShowGraph) setShowGraph(true);
  }, [requestShowGraph]);

  if (!enabled) return null;

  const filteredResults = results.filter((result) => result.score >= minScore);
  const displaySummary = translatedSummary || aiSummary;
  const selectedLang = translatedLang || 'en';
  const isDrilldown = (drilldownStackDepth || 0) > 0;
  const hasGraph = drilldownTree && drilldownTree.children.length > 0;
  const showGraphView = showGraph && hasGraph && onDrilldownNavigate;

  return (
    <>
      <div className={`ai-summary-box ${aiSummaryCollapsed ? 'collapsed' : ''}`}>
        <AiSummaryHeader
          isDrilldown={isDrilldown}
          collapsed={aiSummaryCollapsed}
          showGraph={showGraph}
          aiSummary={aiSummary}
          loading={aiSummaryLoading}
          selectedLang={selectedLang}
          isTranslating={!!isTranslating}
          translatingLang={translatingLang}
          onLanguageChange={onLanguageChange}
          onToggleCollapsed={onToggleCollapsed}
        />
        {!aiSummaryCollapsed && onDrilldownBack && (
          <div className="ai-drilldown-nav-row">
            {hasGraph && (
              <GraphToggleButton showGraph={showGraph} onToggle={() => setShowGraph((prev) => !prev)} />
            )}
            {!showGraph && (
              <DrilldownBreadcrumb
                stackDepth={drilldownStackDepth || 0}
                onBack={onDrilldownBack}
                currentHighlight={drilldownHighlight}
              />
            )}
          </div>
        )}
        {showGraphView ? (
          <DrilldownGraphView
            tree={drilldownTree!}
            activeNodeId={drilldownCurrentNodeId || 'root'}
            onNodeClick={(nodeId) => {
              onDrilldownNavigate!(nodeId);
              setShowGraph(false);
            }}
          />
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
            />
          </>
        )}
      </div>

      <PromptModal show={showPromptModal} aiPrompt={aiPrompt} onClose={onClosePrompt} />
    </>
  );
};
