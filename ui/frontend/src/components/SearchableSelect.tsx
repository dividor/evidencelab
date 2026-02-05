import React, { useState, useRef, useEffect } from 'react';
import '../App.css';

interface SearchableSelectProps {
  label: string;
  options: { value: string; count: number }[];
  selectedValues: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  hideSelectedChips?: boolean;
}

const SelectedItems = ({
  selectedValues,
  options,
  onRemove,
  onClear
}: {
  selectedValues: string[];
  options: { value: string; count: number }[];
  onRemove: (value: string) => void;
  onClear: () => void;
}) => (
  <div className="selected-items">
    {selectedValues.map((value) => {
      const option = options.find((opt) => opt.value === value);
      return (
        <div key={value} className="selected-item">
          <span className="selected-item-text">
            {value.substring(0, 30)}
            {value.length > 30 ? '...' : ''}
            {option ? ` (${option.count})` : ''}
          </span>
          <button
            className="selected-item-remove"
            onClick={() => onRemove(value)}
            aria-label={`Remove ${value}`}
          >
            ×
          </button>
        </div>
      );
    })}
    <button className="clear-all-button" onClick={onClear}>
      Clear all
    </button>
  </div>
);

const DropdownOptions = ({
  isOpen,
  options,
  selectedValues,
  onToggle
}: {
  isOpen: boolean;
  options: { value: string; count: number }[];
  selectedValues: string[];
  onToggle: (value: string) => void;
}) => {
  if (!isOpen) {
    return null;
  }

  if (options.length === 0) {
    return (
      <div className="searchable-select-dropdown">
        <div className="searchable-select-no-results">No results found</div>
      </div>
    );
  }

  return (
    <div className="searchable-select-dropdown">
      {options.map((option) => {
        const isSelected = selectedValues.includes(option.value);
        return (
          <div
            key={option.value}
            className={`searchable-select-option ${isSelected ? 'selected' : ''}`}
            onClick={() => onToggle(option.value)}
          >
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => {}}
              className="searchable-select-checkbox"
            />
            <div className="searchable-select-option-content">
              <span className="searchable-select-option-text">{option.value}</span>
            </div>
            <span className="searchable-select-option-count">({option.count})</span>
          </div>
        );
      })}
    </div>
  );
};

export const SearchableSelect: React.FC<SearchableSelectProps> = ({
  label,
  options,
  selectedValues,
  onChange,
  placeholder = 'Search...',
  hideSelectedChips = false
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredOptions = options.filter((option) =>
    option.value.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleOption = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter(v => v !== value));
    } else {
      onChange([...selectedValues, value]);
    }
  };

  const removeSelected = (value: string) => {
    onChange(selectedValues.filter((v) => v !== value));
  };

  const clearAll = () => {
    onChange([]);
  };

  return (
    <div className="filter-group searchable-select-container" ref={containerRef}>
      <label className="filter-label">{label}</label>

      {!hideSelectedChips && selectedValues.length > 0 && (
        <SelectedItems
          selectedValues={selectedValues}
          options={options}
          onRemove={removeSelected}
          onClear={clearAll}
        />
      )}

      {/* Search input */}
      <div className="searchable-select-input-wrapper">
        <input
          type="text"
          className="searchable-select-input"
          placeholder={placeholder}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onFocus={() => setIsOpen(true)}
        />
        <button
          className="searchable-select-toggle"
          onClick={() => setIsOpen(!isOpen)}
          aria-label="Toggle dropdown"
        >
          {isOpen ? '▲' : '▼'}
        </button>
      </div>

      <DropdownOptions
        isOpen={isOpen}
        options={filteredOptions}
        selectedValues={selectedValues}
        onToggle={toggleOption}
      />
    </div>
  );
};
