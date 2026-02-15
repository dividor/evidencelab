import React from 'react';

type SortDirection = 'asc' | 'desc';

interface SortableHeaderProps {
  columnKey: string;
  label: string;
  filterable?: boolean;
  sortField: string;
  sortDirection: SortDirection;
  onSort: (field: string) => void;
  onFilterClick: (column: string, event: React.MouseEvent<HTMLButtonElement>) => void;
  hasActiveFilter: (column: string) => boolean;
}

export const SortableHeader: React.FC<SortableHeaderProps> = ({
  columnKey,
  label,
  filterable,
  sortField,
  sortDirection,
  onSort,
  onFilterClick,
  hasActiveFilter,
}) => {
  const isSortedAsc = sortField === columnKey && sortDirection === 'asc';
  const isSortedDesc = sortField === columnKey && sortDirection === 'desc';

  return (
    <th className="sortable-header">
      <div className="header-content">
        <span onClick={() => onSort(columnKey)} className="header-label">
          {label.includes('\n') ? (
            <>
              {label.split('\n')[0]}
              <em className="header-label-subtitle">{label.split('\n')[1]}</em>
            </>
          ) : label}
        </span>
        <div className="header-icons">
          <button
            onClick={() => onSort(columnKey)}
            className="sort-icon-button"
            aria-label={`Sort by ${label.toLowerCase()}`}
          >
            <span className="sort-icon-stack">
              <span className={`chevron-up ${isSortedAsc ? 'active' : ''}`}>▲</span>
              <span className={`chevron-down ${isSortedDesc ? 'active' : ''}`}>▼</span>
            </span>
          </button>
          {filterable && (
            <button
              onClick={(event) => onFilterClick(columnKey, event)}
              className={`filter-icon-button ${hasActiveFilter(columnKey) ? 'active' : ''}`}
              aria-label={`Filter ${label.toLowerCase()}`}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M0.5 1.5h11l-4.5 5.25v3.75l-2 1.5v-5.25l-4.5-5.25z"
                  stroke="currentColor"
                  strokeWidth="1"
                  fill="none"
                />
              </svg>
            </button>
          )}
        </div>
      </div>
    </th>
  );
};
