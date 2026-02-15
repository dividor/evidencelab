import React from 'react';
import { Facets, FacetValue } from '../../types/api';

interface SelectedFiltersDisplayProps {
  facets: Facets;
  selectedFilters: Record<string, string[]>;
  onRemove: (coreField: string, value: string) => void;
}

interface FilterSectionsProps {
  facets: Facets;
  selectedFilters: Record<string, string[]>;
  collapsedFilters: Set<string>;
  expandedFilterLists: Set<string>;
  filterSearchTerms: Record<string, string>;
  titleSearchResults: FacetValue[];
  facetSearchResults: Record<string, FacetValue[]>;
  onToggleFilter: (coreField: string) => void;
  onSearchTermChange: (coreField: string, value: string) => void;
  onToggleFilterListExpansion: (coreField: string) => void;
  onFilterValuesChange: (coreField: string, nextValues: string[]) => void;
  renderContentTop?: (coreField: string, displayLabel: string) => React.ReactNode;
}

interface TitleFilterChipProps {
  coreField: string;
  displayLabel: string;
  value: string;
  option?: FacetValue;
  onRemove: (coreField: string, value: string) => void;
}

interface StandardFilterChipProps {
  coreField: string;
  displayLabel: string;
  value: string;
  onRemove: (coreField: string, value: string) => void;
}

interface FilterCheckboxListProps {
  items: FacetValue[];
  selectedValues: string[];
  coreField: string;
  stacked: boolean;
  onChange: (coreField: string, nextValues: string[]) => void;
}

const buildTitleFilterSubtitle = (option?: FacetValue): string => {
  if (!option) return '';
  if (!option.organization && !option.published_year) return '';
  if (option.organization && option.published_year) {
    return `${option.organization} • ${option.published_year}`;
  }
  return option.organization || option.published_year || '';
};

const TitleValue = ({ value }: { value: string }) => {
  const truncated = value.length > 40 ? `${value.substring(0, 40)}...` : value;
  return <span className="filter-chip-value">{truncated}</span>;
};

const TitleSubtitle = ({ option }: { option?: FacetValue }) => {
  const parts = [option?.organization, option?.published_year].filter(Boolean);
  if (parts.length === 0) {
    return null;
  }
  return <span className="filter-chip-subtitle">{parts.join(' • ')}</span>;
};

const TitleFilterChip = ({
  coreField,
  displayLabel,
  value,
  option,
  onRemove,
}: TitleFilterChipProps) => {
  const tooltipSubtitle = buildTitleFilterSubtitle(option);

  return (
    <div
      className="filter-chip filter-chip-with-tooltip"
      data-tooltip={value}
      data-tooltip-subtitle={tooltipSubtitle}
    >
      <div className="filter-chip-content">
        <span className="filter-chip-label">{displayLabel}:</span>
        <div className="filter-chip-text-container">
          <TitleValue value={value} />
          <TitleSubtitle option={option} />
        </div>
      </div>
      <button
        onClick={() => onRemove(coreField, value)}
        className="filter-chip-remove"
        aria-label={`Remove ${value} filter`}
      >
        ×
      </button>
    </div>
  );
};

const StandardFilterChip = ({
  coreField,
  displayLabel,
  value,
  onRemove,
}: StandardFilterChipProps) => (
  <div className="filter-chip">
    <span className="filter-chip-label">{displayLabel}:</span>
    <span className="filter-chip-value">{value}</span>
    <button
      onClick={() => onRemove(coreField, value)}
      className="filter-chip-remove"
      aria-label={`Remove ${value} filter`}
    >
      ×
    </button>
  </div>
);

export const SelectedFiltersDisplay = ({
  facets,
  selectedFilters,
  onRemove,
}: SelectedFiltersDisplayProps) => {
  const hasSelected = Object.entries(selectedFilters).some(
    ([, values]) => values.length > 0
  );

  if (!hasSelected) {
    return null;
  }

  return (
    <div className="selected-filters">
      {Object.entries(facets.filter_fields).map(([coreField, displayLabel]) => {
        const selectedValues = selectedFilters[coreField] || [];
        return selectedValues.map((value) => {
          if (coreField === 'title') {
            const option = facets.facets.title?.find((item) => item.value === value);
            return (
              <TitleFilterChip
                key={`${coreField}-${value}`}
                coreField={coreField}
                displayLabel={displayLabel}
                value={value}
                option={option}
                onRemove={onRemove}
              />
            );
          }
          return (
            <StandardFilterChip
              key={`${coreField}-${value}`}
              coreField={coreField}
              displayLabel={displayLabel}
              value={value}
              onRemove={onRemove}
            />
          );
        });
      })}
    </div>
  );
};

const computeDisplayItems = (
  coreField: string,
  facetValues: FacetValue[],
  searchTerm: string,
  isExpanded: boolean,
  titleSearchResults: FacetValue[],
  facetSearchResults: Record<string, FacetValue[]>
): { displayItems: FacetValue[]; remainingCount: number } => {
  const defaultDisplayCount = 5;

  if (coreField === 'title' && searchTerm.length >= 2 && titleSearchResults.length > 0) {
    const remaining = titleSearchResults.length - defaultDisplayCount;
    return {
      displayItems: isExpanded ? titleSearchResults : titleSearchResults.slice(0, defaultDisplayCount),
      remainingCount: isExpanded ? 0 : remaining,
    };
  }

  if (facetSearchResults[coreField]) {
    const results = facetSearchResults[coreField];
    const remaining = results.length - defaultDisplayCount;
    return {
      displayItems: isExpanded ? results : results.slice(0, defaultDisplayCount),
      remainingCount: isExpanded ? 0 : remaining,
    };
  }

  const filteredItems = facetValues.filter((item) =>
    item.value.toLowerCase().includes(searchTerm)
  );
  const remaining = filteredItems.length - defaultDisplayCount;
  return {
    displayItems: isExpanded ? filteredItems : filteredItems.slice(0, defaultDisplayCount),
    remainingCount: isExpanded ? 0 : remaining,
  };
};

const FilterCheckboxList = ({
  items,
  selectedValues,
  coreField,
  stacked,
  onChange,
}: FilterCheckboxListProps) => (
  <React.Fragment>
    {items.map((item) => (
      <label
        key={item.value}
        className={`filter-checkbox-item${stacked ? ' filter-checkbox-item-stacked' : ''}`}
      >
        <div className="filter-checkbox-row">
          <input
            type="checkbox"
            checked={selectedValues.includes(item.value)}
            onChange={(event) => {
              const nextValues = event.target.checked
                ? [...selectedValues, item.value]
                : selectedValues.filter((value) => value !== item.value);
              onChange(coreField, nextValues);
            }}
          />
          <div className="filter-checkbox-text">
            <span className="filter-checkbox-label" title={stacked ? item.value : undefined}>
              {item.value}
            </span>
            {stacked && (item.organization || item.published_year) && (
              <span className="filter-checkbox-subtitle">
                {item.organization}
                {item.organization && item.published_year && ' • '}
                {item.published_year}
              </span>
            )}
          </div>
          <span className="filter-checkbox-count">({item.count.toLocaleString()})</span>
        </div>
      </label>
    ))}
  </React.Fragment>
);

export const FilterSections = ({
  facets,
  selectedFilters,
  collapsedFilters,
  expandedFilterLists,
  filterSearchTerms,
  titleSearchResults,
  facetSearchResults,
  onToggleFilter,
  onSearchTermChange,
  onToggleFilterListExpansion,
  onFilterValuesChange,
  renderContentTop,
}: FilterSectionsProps) => (
  <React.Fragment>
    {Object.entries(facets.filter_fields).map(([coreField, displayLabel]) => {
      const facetValues = facets.facets[coreField] || [];
      const selectedValues = selectedFilters[coreField] || [];
      const searchTerm = (filterSearchTerms[coreField] || '').toLowerCase();
      const isExpanded = expandedFilterLists.has(coreField);
      const { displayItems, remainingCount } = computeDisplayItems(
        coreField,
        facetValues,
        searchTerm,
        isExpanded,
        titleSearchResults,
        facetSearchResults
      );
      const isCollapsed = collapsedFilters.has(coreField);
      const showContent =
        !isCollapsed && (coreField === 'title' || facetValues.length > 0 || searchTerm.length > 0);

      return (
        <div key={coreField} className="filter-section">
          <div className="filter-section-header" onClick={() => onToggleFilter(coreField)}>
            <span className="filter-section-toggle">{isCollapsed ? '▶' : '▼'}</span>
            <span className="filter-section-title">
              {displayLabel}
              {coreField.startsWith('tag_') && <em className="header-label-subtitle">(AI-generated : Experimental)</em>}
            </span>
          </div>
          {showContent && (
            <div className="filter-section-content">
              <input
                type="text"
                placeholder={`Search ${displayLabel.toLowerCase()}...`}
                value={filterSearchTerms[coreField] || ''}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                  onSearchTermChange(coreField, event.target.value)
                }
                className="filter-search-input"
                onClick={(event: React.MouseEvent) => event.stopPropagation()}
              />
              {renderContentTop?.(coreField, displayLabel)}
              <FilterCheckboxList
                items={displayItems}
                selectedValues={selectedValues}
                coreField={coreField}
                stacked={coreField === 'title'}
                onChange={onFilterValuesChange}
              />
              {remainingCount > 0 && (
                <button
                  className="filter-show-more"
                  onClick={() => onToggleFilterListExpansion(coreField)}
                >
                  {isExpanded ? 'Show less' : `Show ${remainingCount} more`}
                </button>
              )}
            </div>
          )}
        </div>
      );
    })}
  </React.Fragment>
);
