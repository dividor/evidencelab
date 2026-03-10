import React, { useState } from 'react';
import { SearchToolCall } from '../../types/api';
import { SearchSettings } from '../../types/auth';

interface ToolCallPanelProps {
  toolCalls: SearchToolCall[];
  searchSettings?: Partial<SearchSettings> | null;
  rerankerModel?: string | null;
  defaultExpanded?: boolean;
}

/** Format a search setting key/value for display. */
const formatSetting = (key: string, value: unknown): string | null => {
  if (value == null) return null;
  switch (key) {
    case 'denseWeight': return `dense_weight: ${value}`;
    case 'recencyBoost': return value ? 'recency_boost: true' : null;
    case 'recencyWeight': return `recency_weight: ${value}`;
    case 'recencyScaleDays': return `recency_scale_days: ${value}`;
    case 'sectionTypes': {
      const arr = value as string[];
      return arr.length > 0 ? `section_types: [${arr.join(', ')}]` : null;
    }
    case 'keywordBoostShortQueries': return value ? null : 'keyword_boost: false';
    case 'minChunkSize': return (value as number) > 0 ? `min_chunk_size: ${value}` : null;
    default: return null;
  }
};

export const ToolCallPanel: React.FC<ToolCallPanelProps> = ({
  toolCalls,
  searchSettings,
  rerankerModel,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (toolCalls.length === 0) return null;

  const totalResults = toolCalls.reduce((sum, tc) => sum + tc.resultCount, 0);

  // Build display lines for search parameters
  const paramLines: string[] = [];
  if (rerankerModel) {
    paramLines.push(`reranker: ${rerankerModel}`);
  }
  if (searchSettings) {
    for (const [key, value] of Object.entries(searchSettings)) {
      const line = formatSetting(key, value);
      if (line) paramLines.push(line);
    }
  }

  return (
    <div className="tool-call-panel">
      <button
        className="tool-call-panel-toggle"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span className="tool-call-panel-icon">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="tool-call-panel-summary">
          {toolCalls.length} search{toolCalls.length !== 1 ? 'es' : ''} &middot; {totalResults} result{totalResults !== 1 ? 's' : ''}
        </span>
      </button>
      {expanded && (
        <div className="tool-call-panel-code">
          <pre className="tool-call-code-block">
            {toolCalls.map((tc, i) => (
              <div key={i} className="tool-call-code-entry">
                <span className="tool-call-code-query">{tc.query}</span>
                <span className="tool-call-code-result">{tc.resultCount} results</span>
              </div>
            ))}
            {paramLines.length > 0 && (
              <>
                <div className="tool-call-code-separator" />
                {paramLines.map((line, i) => (
                  <div key={`p-${i}`} className="tool-call-code-param">{line}</div>
                ))}
              </>
            )}
          </pre>
        </div>
      )}
    </div>
  );
};
