import React from 'react';

const MULTISELECT_COLUMNS = new Set([
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

/** Checkbox-based multiselect filter with Select All */
const CheckboxMultiselect: React.FC<{
  options: string[];
  selectedValues: Set<string>;
  onToggle: (value: string) => void;
  onToggleAll: () => void;
  onApply: () => void;
  onClear: (() => void) | null;
}> = ({ options, selectedValues, onToggle, onToggleAll, onApply, onClear }) => {
  const allSelected = options.length > 0 && selectedValues.size === options.length;
  const someSelected = selectedValues.size > 0 && selectedValues.size < options.length;

  return (
    <div className="filter-multiselect">
      <div className="filter-multiselect-options">
        <label className="filter-checkbox-item filter-select-all">
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => { if (el) el.indeterminate = someSelected; }}
            onChange={onToggleAll}
          />
          <span>Select all</span>
        </label>
        {options.map((option) => (
          <label key={option} className="filter-checkbox-item">
            <input
              type="checkbox"
              checked={selectedValues.has(option)}
              onChange={() => onToggle(option)}
            />
            <span>{option}</span>
          </label>
        ))}
      </div>
      <div className="filter-actions">
        <button className="filter-apply-button" onClick={onApply}>
          Apply{selectedValues.size > 0 ? ` (${selectedValues.size})` : ''}
        </button>
        {onClear && (
          <button className="filter-clear-button" onClick={onClear}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
};

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
  const isMultiselectFilter = MULTISELECT_COLUMNS.has(activeFilterColumn);

  // Determine if column is a taxonomy from config (not hardcoded)
  const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};
  const isTaxonomyFilter = activeFilterColumn in taxonomies;

  // For multiselect, track selected values as a set
  const [selectedValues, setSelectedValues] = React.useState<Set<string>>(() => {
    const current = columnFilters[activeFilterColumn] || '';
    return new Set(current ? current.split(',').map((v) => v.trim()) : []);
  });

  const options = React.useMemo(
    () => getCategoricalOptions(activeFilterColumn),
    [getCategoricalOptions, activeFilterColumn],
  );

  const toggleValue = (value: string) => {
    setSelectedValues((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedValues.size === options.length) {
      setSelectedValues(new Set());
    } else {
      setSelectedValues(new Set(options));
    }
  };

  const applyMultiselect = () => {
    if (selectedValues.size === 0) {
      onClearFilter(activeFilterColumn);
    } else {
      onApplyFilter(activeFilterColumn, Array.from(selectedValues).join(','));
    }
    onClose();
  };

  const clearAndClose = hasActiveFilter(activeFilterColumn)
    ? () => { onClearFilter(activeFilterColumn); setSelectedValues(new Set()); onClose(); }
    : null;

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
        {(isMultiselectFilter || isTaxonomyFilter) && (
          <CheckboxMultiselect
            options={options}
            selectedValues={selectedValues}
            onToggle={toggleValue}
            onToggleAll={toggleAll}
            onApply={applyMultiselect}
            onClear={clearAndClose}
          />
        )}
      </div>
    </div>
  );
};
