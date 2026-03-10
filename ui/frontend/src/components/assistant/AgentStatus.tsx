import React from 'react';
import { SearchToolCall } from '../../types/api';

interface AgentStatusProps {
  phase: string;
  searchQueries?: string[];
  toolCalls?: SearchToolCall[];
}

const PHASE_CONFIG: Record<string, string> = {
  planning: 'Planning research approach',
  searching: 'Searching documents',
  synthesizing: 'Synthesizing answer',
  reflecting: 'Reflecting on completeness',
};

export const AgentStatus: React.FC<AgentStatusProps> = ({ phase, searchQueries, toolCalls }) => {
  const label = PHASE_CONFIG[phase] || phase;
  const hasSearchDetail = phase === 'searching' && (
    (toolCalls && toolCalls.length > 0) || (searchQueries && searchQueries.length > 0)
  );

  return (
    <div className="agent-status">
      <div className="agent-status-indicator">
        <span className="agent-status-label">{label}</span>
        {!hasSearchDetail && (
          <span className="agent-status-dots">
            <span className="dot">.</span>
            <span className="dot">.</span>
            <span className="dot">.</span>
          </span>
        )}
      </div>
      {hasSearchDetail && (
        <div className="agent-status-detail">
          {toolCalls && toolCalls.map((tc, i) => (
            <div key={`tc-${i}`} className="agent-status-query">
              <span className="agent-status-query-text">{tc.query}</span>
              <span className="agent-status-query-count">{tc.resultCount} results</span>
            </div>
          ))}
          {searchQueries && searchQueries
            .filter((q) => !toolCalls?.some((tc) => tc.query === q))
            .map((q, i) => (
              <div key={`sq-${i}`} className="agent-status-query agent-status-query-pending">
                <span className="agent-status-query-text">{q}</span>
                <span className="agent-status-query-count agent-status-pending-dots">
                  <span className="dot">.</span><span className="dot">.</span><span className="dot">.</span>
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
};
