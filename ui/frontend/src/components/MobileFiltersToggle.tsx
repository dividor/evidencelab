import React from 'react';

interface MobileFiltersToggleProps {
  filtersExpanded: boolean;
  activeFiltersCount: number;
  onToggle: () => void;
  label?: string;
}

export const MobileFiltersToggle = ({
  filtersExpanded,
  activeFiltersCount,
  onToggle,
  label = 'Filters',
}: MobileFiltersToggleProps) => (
  <button
    className="mobile-filters-toggle"
    onClick={onToggle}
    aria-expanded={filtersExpanded}
  >
    <span className="mobile-filters-toggle-icon">
      {filtersExpanded ? '▼' : '▶'}
    </span>
    <span className="mobile-filters-toggle-text">
      {label} {activeFiltersCount > 0 && `(${activeFiltersCount} active)`}
    </span>
  </button>
);
