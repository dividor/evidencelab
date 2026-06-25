import React from 'react';
import { render, screen } from '@testing-library/react';

import { FilterSections } from '../components/filters/FilterComponents';
import { Facets } from '../types/api';

// Regression test for the filter-value hover tooltips (issue 331944).
// Truncated filter values must expose their full text via a native `title`
// attribute so hovering reveals the complete value on every filter screen.

const LONG_COUNTRY = 'Democratic Republic of the Congo (long enough to truncate)';

const buildFacets = (): Facets => ({
  facets: {
    country: [{ value: LONG_COUNTRY, count: 7 }],
    tag_theme: [{ value: 'theme_1 - Food Security and Nutrition', count: 4 }],
  },
  filter_fields: {
    country: 'Country',
    tag_theme: 'Theme',
  },
});

const renderSections = () =>
  render(
    <FilterSections
      facets={buildFacets()}
      selectedFilters={{}}
      rangeFilters={{}}
      // `isCollapsed = !collapsedFilters.has(field)`, so membership means expanded.
      collapsedFilters={new Set(['country', 'tag_theme'])}
      expandedFilterLists={new Set()}
      filterSearchTerms={{}}
      titleSearchResults={[]}
      facetSearchResults={{}}
      onToggleFilter={() => {}}
      onSearchTermChange={() => {}}
      onToggleFilterListExpansion={() => {}}
      onFilterValuesChange={() => {}}
      onRangeChange={() => {}}
    />
  );

describe('FilterSections value tooltips', () => {
  it('test_standard_filter_value_when_rendered_then_exposes_full_text_title', () => {
    renderSections();
    const label = screen.getByText(LONG_COUNTRY);
    expect(label).toHaveAttribute('title', LONG_COUNTRY);
  });

  it('test_tag_filter_value_when_rendered_then_title_matches_stripped_label', () => {
    renderSections();
    const stripped = 'Food Security and Nutrition';
    const label = screen.getByText(stripped);
    expect(label).toHaveAttribute('title', stripped);
  });
});
