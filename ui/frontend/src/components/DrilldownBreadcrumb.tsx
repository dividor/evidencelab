import React from 'react';

interface DrilldownBreadcrumbProps {
  stackDepth: number;
  onBack: () => void;
  currentHighlight?: string;
}

export const DrilldownBreadcrumb: React.FC<DrilldownBreadcrumbProps> = ({
  stackDepth,
  onBack,
  currentHighlight,
}) => {
  if (stackDepth === 0) return null;

  return (
    <div className="ai-drilldown-breadcrumb">
      <button className="ai-drilldown-back-btn" onClick={onBack}>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="15 18 9 12 15 6" />
        </svg>
        Back to previous summary
      </button>
      {currentHighlight && (
        <span className="ai-drilldown-context">
          Exploring: &ldquo;{currentHighlight}&rdquo;
        </span>
      )}
    </div>
  );
};
