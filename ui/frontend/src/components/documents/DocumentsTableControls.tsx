import React from 'react';

interface DocumentsTableControlsProps {
  filterText: string;
  onFilterTextChange: (value: string) => void;
  selectedCategory: string | null;
  chartView: string;
  currentPage: number;
  pageSize: number;
  totalCount: number;
  loadingTable: boolean;
  onRefresh: () => void;
  onClearCategory: () => void;
}

export const DocumentsTableControls: React.FC<DocumentsTableControlsProps> = ({
  filterText,
  onFilterTextChange,
  selectedCategory,
  chartView,
  currentPage,
  pageSize,
  totalCount,
  loadingTable,
  onRefresh,
  onClearCategory,
}) => {
  const startIndex = (currentPage - 1) * pageSize + 1;
  const endIndex = Math.min(currentPage * pageSize, totalCount);

  return (
    <div className="table-controls">
      <input
        type="text"
        className="table-filter-input"
        placeholder="Search by title"
        value={filterText}
        onChange={(event) => onFilterTextChange(event.target.value)}
      />
      {selectedCategory && (
        <button className="clear-filter-button" onClick={onClearCategory}>
          Clear Category Filter: {selectedCategory}
        </button>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span className="table-count">
          Showing {startIndex}-{endIndex} of {totalCount} documents
          {selectedCategory && ` (filtered by ${chartView})`}
        </span>
        <button
          className="refresh-table-button"
          onClick={onRefresh}
          title="Refresh table content"
          disabled={loadingTable}
          aria-label="Refresh table"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M23 4v6h-6"></path>
            <path d="M1 20v-6h6"></path>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
        </button>
      </div>
    </div>
  );
};
