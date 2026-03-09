import React from 'react';

interface AgentStatusProps {
  phase: string;
}

const PHASE_CONFIG: Record<string, string> = {
  planning: 'Planning research approach',
  searching: 'Searching documents',
  synthesizing: 'Synthesizing answer',
  reflecting: 'Reflecting on completeness',
};

export const AgentStatus: React.FC<AgentStatusProps> = ({ phase }) => {
  const label = PHASE_CONFIG[phase] || phase;

  return (
    <div className="agent-status">
      <div className="agent-status-indicator">
        <span className="agent-status-label">{label}</span>
        <span className="agent-status-dots">
          <span className="dot">.</span>
          <span className="dot">.</span>
          <span className="dot">.</span>
        </span>
      </div>
    </div>
  );
};
