import React from 'react';
import type { FilterColumn } from './useTocValidator';

/** Friendly labels for the review-verdict filter options. */
const REVIEW_LABELS: Record<string, string> = {
  pass: 'Pass',
  fail: 'Fail',
  skipped: 'Skipped',
  untested: 'Not tested',
};

const COLUMN_LABELS: Record<FilterColumn, string> = {
  title: 'title',
  organization: 'organization',
  status: 'status',
  review: 'review',
};

const formatOption = (column: FilterColumn, value: string): string =>
  column === 'review' ? REVIEW_LABELS[value] || value : value;

interface TocValidatorFilterPopoverProps {
  column: FilterColumn;
  position: { top: number; left: number };
  currentValue: string;
  options: string[];
  onApply: (column: FilterColumn, value: string) => void;
  onClear: (column: FilterColumn) => void;
  onClose: () => void;
}

/** Text filter (title) — reuses the Documents Library popover styling. */
const TextFilter: React.FC<{
  column: FilterColumn;
  currentValue: string;
  onApply: (column: FilterColumn, value: string) => void;
  onClear: (column: FilterColumn) => void;
}> = ({ column, currentValue, onApply, onClear }) => {
  const [text, setText] = React.useState(currentValue);
  return (
    <div className="filter-text-input">
      <input
        type="text"
        placeholder="Enter search text..."
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onApply(column, text.trim());
        }}
        autoFocus
      />
      <div className="filter-actions">
        <button className="filter-apply-button" onClick={() => onApply(column, text.trim())}>
          Apply
        </button>
        {currentValue && (
          <button className="filter-clear-button" onClick={() => onClear(column)}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
};

/** Checkbox multiselect (organization / status / review). */
const MultiselectFilter: React.FC<{
  column: FilterColumn;
  currentValue: string;
  options: string[];
  onApply: (column: FilterColumn, value: string) => void;
  onClear: (column: FilterColumn) => void;
}> = ({ column, currentValue, options, onApply, onClear }) => {
  const [selected, setSelected] = React.useState<Set<string>>(
    () => new Set(currentValue ? currentValue.split(',').map((v) => v.trim()) : [])
  );

  const toggle = (value: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) => (prev.size === options.length ? new Set() : new Set(options)));

  const allSelected = options.length > 0 && selected.size === options.length;
  const someSelected = selected.size > 0 && selected.size < options.length;

  return (
    <div className="filter-multiselect">
      <div className="filter-multiselect-options">
        <label className="filter-checkbox-item filter-select-all">
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected;
            }}
            onChange={toggleAll}
          />
          <span>Select all</span>
        </label>
        {options.map((option) => (
          <label key={option} className="filter-checkbox-item">
            <input
              type="checkbox"
              checked={selected.has(option)}
              onChange={() => toggle(option)}
            />
            <span>{formatOption(column, option)}</span>
          </label>
        ))}
      </div>
      <div className="filter-actions">
        <button
          className="filter-apply-button"
          onClick={() => onApply(column, Array.from(selected).join(','))}
        >
          Apply{selected.size > 0 ? ` (${selected.size})` : ''}
        </button>
        {currentValue && (
          <button className="filter-clear-button" onClick={() => onClear(column)}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
};

export const TocValidatorFilterPopover: React.FC<TocValidatorFilterPopoverProps> = ({
  column,
  position,
  currentValue,
  options,
  onApply,
  onClear,
  onClose,
}) => (
  <>
    <div className="filter-popover-backdrop" onClick={onClose} />
    <div
      className="filter-popover"
      style={{ position: 'absolute', top: `${position.top}px`, left: `${position.left}px` }}
    >
      <div className="filter-popover-header">
        <span>Filter {COLUMN_LABELS[column]}</span>
        <button className="filter-popover-close" onClick={onClose} aria-label="Close filter">
          ×
        </button>
      </div>
      <div className="filter-popover-content">
        {column === 'title' ? (
          <TextFilter
            column={column}
            currentValue={currentValue}
            onApply={onApply}
            onClear={onClear}
          />
        ) : (
          <MultiselectFilter
            column={column}
            currentValue={currentValue}
            options={options}
            onApply={onApply}
            onClear={onClear}
          />
        )}
      </div>
    </div>
  </>
);

export default TocValidatorFilterPopover;
