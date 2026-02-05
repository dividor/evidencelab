import React from 'react';

const FILTER_LIST_COLUMNS = new Set([
  'title',
  'organization',
  'document_type',
  'published_year',
  'language',
  'file_format',
  'status',
]);

interface DocumentsFilterPopoverProps {
  activeFilterColumn: string;
  filterPopoverPosition: { top: number; left: number };
  tempColumnFilters: Record<string, string>;
  columnFilters: Record<string, string>;
  onTempFilterChange: (column: string, value: string) => void;
  onApplyFilter: (column: string, value: string) => void;
  onClearFilter: (column: string) => void;
  hasActiveFilter: (column: string) => boolean;
  getCategoricalOptions: (column: string) => string[];
  onClose: () => void;
  dataSourceConfig?: any; // Config to determine taxonomy columns dynamically
}

export const DocumentsFilterPopover: React.FC<DocumentsFilterPopoverProps> = ({
  activeFilterColumn,
  filterPopoverPosition,
  tempColumnFilters,
  columnFilters,
  onTempFilterChange,
  onApplyFilter,
  onClearFilter,
  hasActiveFilter,
  getCategoricalOptions,
  onClose,
  dataSourceConfig,
}) => {
  const isTextFilter = activeFilterColumn === 'error_message';
  const isListFilter = FILTER_LIST_COLUMNS.has(activeFilterColumn);

  // Determine if column is a taxonomy from config (not hardcoded)
  const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};
  const isTaxonomyFilter = activeFilterColumn in taxonomies;

  // For multiselect, track selected values as a set
  const [selectedValues, setSelectedValues] = React.useState<Set<string>>(() => {
    const current = columnFilters[activeFilterColumn] || '';
    return new Set(current ? current.split(',').map((v) => v.trim()) : []);
  });

  const toggleValue = (value: string) => {
    const newSelected = new Set(selectedValues);
    if (newSelected.has(value)) {
      newSelected.delete(value);
    } else {
      newSelected.add(value);
    }
    setSelectedValues(newSelected);
  };

  const applyMultiselect = () => {
    if (selectedValues.size === 0) {
      onClearFilter(activeFilterColumn);
    } else {
      const filterValue = Array.from(selectedValues).join(',');
      onApplyFilter(activeFilterColumn, filterValue);
    }
    onClose();
  };

  return (
    <div
      className="filter-popover"
      style={{
        position: 'absolute',
        top: `${filterPopoverPosition.top}px`,
        left: `${filterPopoverPosition.left}px`,
      }}
    >
      <div className="filter-popover-header">
        <span>Filter {activeFilterColumn.replace('_', ' ')}</span>
        <button className="filter-popover-close" onClick={onClose} aria-label="Close filter">
          ×
        </button>
      </div>
      <div className="filter-popover-content">
        {isTextFilter && (
          <div className="filter-text-input">
            <input
              type="text"
              placeholder="Enter search text..."
              value={tempColumnFilters[activeFilterColumn] || ''}
              onChange={(event) => onTempFilterChange(activeFilterColumn, event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  onApplyFilter(activeFilterColumn, tempColumnFilters[activeFilterColumn] || '');
                }
              }}
              autoFocus
            />
            <div className="filter-actions">
              <button
                className="filter-apply-button"
                onClick={() =>
                  onApplyFilter(activeFilterColumn, tempColumnFilters[activeFilterColumn] || '')
                }
              >
                Apply
              </button>
              {hasActiveFilter(activeFilterColumn) && (
                <button className="filter-clear-button" onClick={() => onClearFilter(activeFilterColumn)}>
                  Clear
                </button>
              )}
            </div>
          </div>
        )}
        {isListFilter && (
          <div className="filter-list">
            <div
              className={`filter-list-item ${!columnFilters[activeFilterColumn] ? 'selected' : ''}`}
              onClick={() => onClearFilter(activeFilterColumn)}
            >
              <span>All</span>
            </div>
            {getCategoricalOptions(activeFilterColumn).map((option) => (
              <div
                key={option}
                className={`filter-list-item ${
                  columnFilters[activeFilterColumn] === option ? 'selected' : ''
                }`}
                onClick={() => onApplyFilter(activeFilterColumn, option)}
              >
                <span>{option}</span>
              </div>
            ))}
          </div>
        )}
        {isTaxonomyFilter && (
          <div className="filter-multiselect">
            <div className="filter-multiselect-options">
              {getCategoricalOptions(activeFilterColumn).map((option) => (
                <label key={option} className="filter-checkbox-item">
                  <input
                    type="checkbox"
                    checked={selectedValues.has(option)}
                    onChange={() => toggleValue(option)}
                  />
                  <span>{option}</span>
                </label>
              ))}
            </div>
            <div className="filter-actions">
              <button className="filter-apply-button" onClick={applyMultiselect}>
                Apply ({selectedValues.size})
              </button>
              {hasActiveFilter(activeFilterColumn) && (
                <button className="filter-clear-button" onClick={() => {
                  onClearFilter(activeFilterColumn);
                  setSelectedValues(new Set());
                  onClose();
                }}>
                  Clear
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
