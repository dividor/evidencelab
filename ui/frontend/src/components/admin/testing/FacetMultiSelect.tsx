import React, { useState } from 'react';

interface FacetMultiSelectProps {
  options: string[];
  value: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

const MAX_SUGGESTIONS = 20;

/**
 * Multiselect over a fixed list of facet values (e.g. country / region).
 *
 * Selected values render as removable chips; typing filters the remaining
 * options. Unlike {@link DocumentTitleSelect} the options are provided
 * synchronously (from the data source's facets) rather than fetched per query.
 */
const FacetMultiSelect: React.FC<FacetMultiSelectProps> = ({
  options,
  value,
  onChange,
  placeholder,
}) => {
  const [term, setTerm] = useState('');

  const add = (option: string) => {
    if (!value.includes(option)) onChange([...value, option]);
    setTerm('');
  };

  const remove = (option: string) => {
    onChange(value.filter((v) => v !== option));
  };

  const needle = term.trim().toLowerCase();
  const matches = options
    .filter((opt) => !value.includes(opt))
    .filter((opt) => !needle || opt.toLowerCase().includes(needle))
    .slice(0, MAX_SUGGESTIONS);

  return (
    <div className="testing-doc-select">
      {value.length > 0 && (
        <div className="testing-case-tags" style={{ marginBottom: '0.4rem' }}>
          {value.map((option) => (
            <span key={option} className="testing-tag" title={option}>
              {option}
              <button
                type="button"
                className="testing-tag-remove"
                aria-label={`Remove ${option}`}
                onClick={() => remove(option)}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder={placeholder || 'Type to filter…'}
      />
      {term.trim() !== '' && matches.length > 0 && (
        <ul className="testing-doc-suggestions">
          {matches.map((option) => (
            <li key={option}>
              <button
                type="button"
                className="testing-doc-suggestion"
                onClick={() => add(option)}
              >
                {option}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default FacetMultiSelect;
