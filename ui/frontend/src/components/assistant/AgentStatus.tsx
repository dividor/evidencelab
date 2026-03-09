import React from 'react';

interface AgentStatusProps {
  phase: string;
  searchQueries?: string[];
}

const PHASE_CONFIG: Record<string, { icon: string; label: string }> = {
  planning: { icon: '\uD83D\uDD0D', label: 'Planning research approach...' },
  searching: { icon: '\uD83D\uDCDA', label: 'Searching documents...' },
  synthesizing: { icon: '\u270D\uFE0F', label: 'Synthesizing answer...' },
  reflecting: { icon: '\uD83E\uDD14', label: 'Reflecting on completeness...' },
};

export const AgentStatus: React.FC<AgentStatusProps> = ({ phase, searchQueries }) => {
  const config = PHASE_CONFIG[phase] || { icon: '\u23F3', label: phase };

  return (
    <div className="agent-status">
      <div className="agent-status-indicator">
        <span className="agent-status-icon">{config.icon}</span>
        <span className="agent-status-label">{config.label}</span>
        <span className="agent-status-dots">
          <span className="dot">.</span>
          <span className="dot">.</span>
          <span className="dot">.</span>
        </span>
      </div>
      {phase === 'searching' && searchQueries && searchQueries.length > 0 && (
        <div className="agent-status-queries">
          {searchQueries.map((q, i) => (
            <span key={i} className="agent-status-query-chip">{q}</span>
          ))}
        </div>
      )}
    </div>
  );
};
