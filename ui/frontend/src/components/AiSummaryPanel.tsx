import React, { useRef } from 'react';
import { SearchResult } from '../types/api';
import { LANGUAGES } from '../constants';
import { RainbowText } from './RainbowText';
import { AiSummaryWithCitations } from './AiSummaryWithCitations';
import { AiSummaryReferences } from './AiSummaryReferences';
import { DigDeeperPopover } from './DigDeeperPopover';
import { DrilldownBreadcrumb } from './DrilldownBreadcrumb';

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
}: {
  expanded: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
  contentRef?: React.RefObject<HTMLDivElement | null>;
  onDrilldown?: (text: string) => void;
  loading?: boolean;
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
}: {
  collapsed: boolean;
  expanded: boolean;
  loading: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
  contentRef?: React.RefObject<HTMLDivElement | null>;
  onDrilldown?: (text: string) => void;
}) => {
  if (collapsed) {
    return null;
  }

  if (loading) {
    return <AiSummaryLoading expanded={expanded} summary={summary} />;
  }

  if (!summary) {
    return null;
  }

  return (
    <AiSummaryBody
      expanded={expanded}
      summary={summary}
      filteredResults={filteredResults}
      onResultClick={onResultClick}
      contentRef={contentRef}
      onDrilldown={onDrilldown}
      loading={loading}
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
  if (collapsed || (!summary && !loading)) {
    return null;
  }

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
  if (!show) {
    return null;
  }

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
}: AiSummaryPanelProps) => {
  const summaryContentRef = useRef<HTMLDivElement>(null);

  if (!enabled) {
    return null;
  }

  const filteredResults = results.filter((result) => result.score >= minScore);
  const displaySummary = translatedSummary || aiSummary;
  const selectedLang = translatedLang || 'en';
  const isDrilldown = (drilldownStackDepth || 0) > 0;

  return (
    <>
      <div className={`ai-summary-box ${aiSummaryCollapsed ? 'collapsed' : ''}`}>
        <div className="ai-summary-header" onClick={onToggleCollapsed}>
          <h3 className="ai-summary-title">
            {isDrilldown ? 'AI Drilldown Summary' : 'AI Summary'}
          </h3>
          {aiSummary && !aiSummaryLoading && onLanguageChange && (
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
          )}
          <button className="ai-summary-toggle" type="button">
            {aiSummaryCollapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>
        {!aiSummaryCollapsed && onDrilldownBack && (
          <DrilldownBreadcrumb
            stackDepth={drilldownStackDepth || 0}
            onBack={onDrilldownBack}
            currentHighlight={drilldownHighlight}
          />
        )}
        <AiSummaryContent
          collapsed={aiSummaryCollapsed}
          expanded={aiSummaryExpanded}
          loading={aiSummaryLoading}
          summary={displaySummary}
          filteredResults={filteredResults}
          onResultClick={onResultClick}
          contentRef={summaryContentRef}
          onDrilldown={onDrilldown}
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
      </div>

      <PromptModal show={showPromptModal} aiPrompt={aiPrompt} onClose={onClosePrompt} />
    </>
  );
};
