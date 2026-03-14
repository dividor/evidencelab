import React from 'react';

interface DrilldownBreadcrumbProps {
  stackDepth: number;
  onBack: () => void;
  currentHighlight?: string;
}

export const DrilldownBreadcrumb: React.FC<DrilldownBreadcrumbProps> = ({
  stackDepth,
  currentHighlight,
}) => {
  if (stackDepth === 0) return null;

  return (
    <div className="ai-drilldown-breadcrumb">
      {currentHighlight && (
        <span className="ai-drilldown-context">
          Exploring: &ldquo;{currentHighlight}&rdquo;
        </span>
      )}
    </div>
  );
};
