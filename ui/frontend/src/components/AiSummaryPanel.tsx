import React from 'react';
import { SearchResult } from '../types/api';
import { AiSummaryWithCitations } from './AiSummaryWithCitations';
import { AiSummaryReferences } from './AiSummaryReferences';

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
  onToggleCollapsed: () => void;
  onToggleExpanded: () => void;
  onResultClick: (result: SearchResult) => void;
  onOpenPrompt: () => void;
  onClosePrompt: () => void;
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
}: {
  expanded: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}) => (
  <div className={`ai-summary-content ${expanded ? 'expanded' : ''}`}>
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
  </div>
);

const AiSummaryContent = ({
  collapsed,
  expanded,
  loading,
  summary,
  filteredResults,
  onResultClick,
}: {
  collapsed: boolean;
  expanded: boolean;
  loading: boolean;
  summary: string;
  filteredResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
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
  onToggleCollapsed,
  onToggleExpanded,
  onResultClick,
  onOpenPrompt,
  onClosePrompt,
}: AiSummaryPanelProps) => {
  if (!enabled) {
    return null;
  }

  const filteredResults = results.filter((result) => result.score >= minScore);

  return (
    <>
      <div className={`ai-summary-box ${aiSummaryCollapsed ? 'collapsed' : ''}`}>
        <div className="ai-summary-header" onClick={onToggleCollapsed}>
          <h3 className="ai-summary-title">AI Summary</h3>
          <button className="ai-summary-toggle" type="button">
            {aiSummaryCollapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>
        <AiSummaryContent
          collapsed={aiSummaryCollapsed}
          expanded={aiSummaryExpanded}
          loading={aiSummaryLoading}
          summary={aiSummary}
          filteredResults={filteredResults}
          onResultClick={onResultClick}
        />
        <AiSummaryFooter
          collapsed={aiSummaryCollapsed}
          summary={aiSummary}
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
