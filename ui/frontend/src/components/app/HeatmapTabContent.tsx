import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import * as XLSX from 'xlsx';
import API_BASE_URL, {
  SEARCH_RESULTS_PAGE_SIZE,
  SEARCH_SEMANTIC_HIGHLIGHTS,
  SEMANTIC_HIGHLIGHT_THRESHOLD,
} from '../../config';
import {
  Facets,
  FacetValue,
  SearchFilters,
  SearchResponse,
  SearchResult,
  SummaryModelConfig,
} from '../../types/api';
import { FiltersPanel } from '../filters/FiltersPanel';
import { FilterSections } from '../filters/FilterComponents';
import { MobileFiltersToggle } from '../MobileFiltersToggle';
import { SearchResultsList } from '../SearchResultsList';
import { RainbowText } from '../RainbowText';
import { findSemanticMatches, TextMatch } from '../../utils/textHighlighting';

const API_KEY = process.env.REACT_APP_API_KEY;

type HeatmapFilterModalState = {
  field: string;
  label: string;
  initialSelectedValues: string[];
};

interface HeatmapTabContentProps {
  selectedDomain: string;
  loadingConfig: boolean;
  facetsDataSource: string | null;
  filtersExpanded: boolean;
  activeFiltersCount: number;
  onToggleFiltersExpanded: () => void;
  onClearFilters: () => void;
  facets: Facets | null;
  filters: SearchFilters;
  selectedFilters: Record<string, string[]>;
  collapsedFilters: Set<string>;
  expandedFilterLists: Set<string>;
  filterSearchTerms: Record<string, string>;
  titleSearchResults: FacetValue[];
  facetSearchResults: Record<string, FacetValue[]>;
  onRemoveFilter: (coreField: string, value: string) => void;
  onToggleFilter: (coreField: string) => void;
  onFilterSearchTermChange: (coreField: string, value: string) => void;
  onToggleFilterListExpansion: (coreField: string) => void;
  onFilterValuesChange: (coreField: string, nextValues: string[]) => void;
  searchModel: string | null;
  searchDenseWeight: number;
  onSearchDenseWeightChange: (value: number) => void;
  keywordBoostShortQueries: boolean;
  onKeywordBoostChange: (value: boolean) => void;
  semanticHighlighting: boolean;
  onSemanticHighlightingChange: (value: boolean) => void;
  semanticHighlightModelConfig?: SummaryModelConfig | null;
  minScore: number;
  maxScore: number;
  onMinScoreChange: (value: number) => void;
  rerankEnabled: boolean;
  onRerankToggle: (value: boolean) => void;
  recencyBoostEnabled: boolean;
  onRecencyBoostToggle: (value: boolean) => void;
  recencyWeight: number;
  onRecencyWeightChange: (value: number) => void;
  recencyScaleDays: number;
  onRecencyScaleDaysChange: (value: number) => void;
  rerankModel: string | null;
  minChunkSize: number;
  onMinChunkSizeChange: (value: number) => void;
  sectionTypes: string[];
  onSectionTypesChange: (next: string[]) => void;
  dataSource: string;
  selectedDoc: SearchResult | null;
  onResultClick: (result: SearchResult) => void;
  onOpenMetadata: (result: SearchResult) => void;
  onLanguageChange: (result: SearchResult, newLang: string) => void;
  onRequestHighlight?: (chunkId: string, text: string) => void;
}

type CellResult = {
  results: SearchResult[];
  count: number;
};

type RawCellResults = Record<string, SearchResult[]>;

const buildCellKey = (rowKey: string, columnValue: string) => `${rowKey}::${columnValue}`;

const buildExcludedFilterFields = (rowDimension: string, columnDimension: string) => {
  const excludedFields = new Set<string>();
  if (rowDimension !== 'queries') {
    excludedFields.add(rowDimension);
  }
  excludedFields.add(columnDimension);
  return excludedFields;
};

const buildSearchParams = (options: {
  cellQuery: string;
  rowDimension: string;
  rowValue: string;
  columnDimension: string;
  columnValue: string;
  filterEntries: [string, string | null | undefined][];
  searchDenseWeight: number;
  rerankEnabled: boolean;
  recencyBoostEnabled: boolean;
  recencyWeight: number;
  recencyScaleDays: number;
  sectionTypes: string[];
  keywordBoostShortQueries: boolean;
  minChunkSize: number;
  rerankModel: string | null;
  searchModel: string | null;
  dataSource: string;
}) => {
  const params = new URLSearchParams({ q: options.cellQuery, limit: SEARCH_RESULTS_PAGE_SIZE });
  for (const [field, value] of options.filterEntries) {
    if (value) {
      params.append(field, value);
    }
  }
  if (options.rowDimension !== 'queries') {
    params.append(options.rowDimension, options.rowValue);
  }
  params.append(options.columnDimension, options.columnValue);
  params.append('dense_weight', options.searchDenseWeight.toString());
  params.append('rerank', options.rerankEnabled.toString());
  params.append('recency_boost', options.recencyBoostEnabled.toString());
  params.append('recency_weight', options.recencyWeight.toString());
  params.append('recency_scale_days', options.recencyScaleDays.toString());
  if (options.sectionTypes.length > 0) {
    params.append('section_types', options.sectionTypes.join(','));
  }
  params.append('keyword_boost_short_queries', options.keywordBoostShortQueries.toString());
  if (options.minChunkSize > 0) {
    params.append('min_chunk_size', options.minChunkSize.toString());
  }
  if (options.rerankModel) {
    params.append('rerank_model', options.rerankModel);
  }
  if (options.searchModel) {
    params.append('model', options.searchModel);
  }
  params.append('data_source', options.dataSource);
  return params;
};

const runTasksInBatches = async (tasks: Array<() => Promise<void>>) => {
  const delayBetweenBatchesMs = 500;
  const batchSize = 3;
  const sleep = (ms: number) => new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });

  for (let i = 0; i < tasks.length; i += batchSize) {
    const batch = tasks.slice(i, i + batchSize);
    await Promise.all(batch.map((task) => task()));
    if (i + batchSize < tasks.length) {
      await sleep(delayBetweenBatchesMs);
    }
  }
};

const resolveResultTitle = (result: SearchResult) =>
  result.title || result.metadata?.title || 'Untitled';

const resolveResultPageLabel = (result: SearchResult) => {
  const page = result.page_num ?? result.metadata?.page;
  return page ? `p. ${page}` : 'page n/a';
};

const resolveResultUrl = (result: SearchResult) =>
  result.pdf_url ||
  result.metadata?.pdf_url ||
  result.metadata?.document_url ||
  result.metadata?.url ||
  '';

const resolveResultExcerpt = (result: SearchResult) =>
  (result.text || '').replace(/\n\n+/g, '\n').trim() || 'No excerpt';

const formatHeatmapResultLine = (result: SearchResult, idx: number) => {
  const title = resolveResultTitle(result);
  const pageLabel = resolveResultPageLabel(result);
  const url = resolveResultUrl(result) || 'n/a';
  const excerpt = resolveResultExcerpt(result);
  return `${idx + 1}. ${title} (${pageLabel})\nURL: ${url}\nExcerpt: ${excerpt}`;
};

const formatHeatmapCellValue = (results: SearchResult[]) => {
  if (results.length === 0) {
    return '';
  }
  return results
    .map((result, idx) => formatHeatmapResultLine(result, idx))
    .join('\n====================\n');
};

const applyHeatmapHeaderStyles = (worksheet: XLSX.WorkSheet) => {
  const range = XLSX.utils.decode_range(worksheet['!ref'] || 'A1');
  const headerStyle = {
    font: { color: { rgb: 'FFFFFF' }, bold: true },
    fill: { fgColor: { rgb: '1F2A44' } },
    alignment: { wrapText: true, vertical: 'top' }
  };

  for (let col = range.s.c; col <= range.e.c; col += 1) {
    const cellAddress = XLSX.utils.encode_cell({ r: 0, c: col });
    if (worksheet[cellAddress]) {
      worksheet[cellAddress].s = headerStyle;
    }
  }

  for (let row = 1; row <= range.e.r; row += 1) {
    const cellAddress = XLSX.utils.encode_cell({ r: row, c: 0 });
    if (worksheet[cellAddress]) {
      worksheet[cellAddress].s = headerStyle;
    }
  }
};

const getContentGridClass = (filtersExpanded: boolean) =>
  `content-grid ${filtersExpanded ? '' : 'content-grid-no-filters'}`;

type FiltersPanelProps = Omit<
  React.ComponentProps<typeof FiltersPanel>,
  'filtersExpanded' | 'onClearFilters'
>;

type HeatmapFiltersColumnProps = {
  filtersExpanded: boolean;
  onToggleFiltersExpanded: () => void;
  onClearFilters: () => void;
  filtersPanelProps: FiltersPanelProps;
};

const HeatmapFiltersColumn = ({
  filtersExpanded,
  onToggleFiltersExpanded,
  onClearFilters,
  filtersPanelProps,
}: HeatmapFiltersColumnProps) => {
  if (!filtersExpanded) {
    return null;
  }
  return (
    <div className="heatmap-filters-column">
      <button
        className="heatmap-filters-tab heatmap-filters-tab-close"
        onClick={onToggleFiltersExpanded}
        aria-label="Hide filters"
        title="Hide filters"
      >
        ›
      </button>
      <FiltersPanel
        {...filtersPanelProps}
        filtersExpanded={filtersExpanded}
        onClearFilters={onClearFilters}
      />
    </div>
  );
};

const HeatmapFiltersTabButton = ({
  filtersExpanded,
  onToggleFiltersExpanded,
}: {
  filtersExpanded: boolean;
  onToggleFiltersExpanded: () => void;
}) => {
  if (filtersExpanded) {
    return null;
  }
  return (
    <button className="heatmap-filters-tab" onClick={onToggleFiltersExpanded}>
      Global Filters
    </button>
  );
};

const HeatmapSearchButtonContent = ({ gridLoading }: { gridLoading: boolean }) => {
  if (!gridLoading) {
    return <span>Heatmap Search</span>;
  }
  return (
    <>
      {Array.from('Searching...').map((char, index) => (
        <span
          key={index}
          className="wave-char"
          style={{ animationDelay: `${index * 0.1}s` }}
        >
          {char}
        </span>
      ))}
    </>
  );
};

const HeatmapActionButtons = ({
  hasCompletedGridSearch,
  handleDownloadExcel,
  executeGridSearch,
  gridLoading,
  hasGridSearchQuery,
}: {
  hasCompletedGridSearch: boolean;
  handleDownloadExcel: () => void;
  executeGridSearch: () => void;
  gridLoading: boolean;
  hasGridSearchQuery: boolean;
}) => (
  <div className="heatmap-actions">
    {hasCompletedGridSearch && (
      <button
        className="heatmap-download-button"
        onClick={handleDownloadExcel}
        type="button"
      >
        <span className="heatmap-download-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" focusable="false">
            <path
              d="M10 2a1 1 0 0 1 1 1v7.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42l2.3 2.3V3a1 1 0 0 1 1-1zm-6 12a1 1 0 0 1 1 1v2h10v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z"
              fill="currentColor"
            />
          </svg>
        </span>
        Download Heatmap
      </button>
    )}
    <button
      className="search-button heatmap-search-button"
      onClick={executeGridSearch}
      disabled={gridLoading || !hasGridSearchQuery}
    >
      <HeatmapSearchButtonContent gridLoading={gridLoading} />
    </button>
  </div>
);

type HeatmapTableProps = {
  rowDimension: string;
  rowOptions: { value: string; label: string }[];
  filteredRowValues: string[];
  filteredColumnValues: string[];
  columnDimension: string;
  columnHeaderLabel: string;
  gridQuery: string;
  setGridQuery: (value: string) => void;
  rowQueries: string[];
  rowTitleSelections: Record<number, FacetValue>;
  rowTitleInputRefs: React.MutableRefObject<Record<number, HTMLInputElement | null>>;
  handleRowQueryChange: (rowIndex: number, value: string) => void;
  handleAddRow: () => void;
  handleRemoveRow: (rowIndex: number) => void;
  handleRowTitleSelectionClear: (rowIndex: number) => void;
  handleRowTitleSelectionCommit: (rowIndex: number, value: string) => void;
  openHeatmapFilterModal: (field: string, label: string) => void;
  isHeatmapFieldFiltered: (field: string) => boolean;
  filteredGridResults: Record<string, CellResult>;
  maxCellCount: number;
  gridLoading: boolean;
  openCellModal: (rowIndex: number, columnValue: string) => void;
};

// Mapping from old SDG names to new SDG names with number prefix
const SDG_NAME_MAPPING: Record<string, string> = {
  'No Poverty': 'SDG1 - No Poverty',
  'Zero Hunger': 'SDG2 - Zero Hunger',
  'Good Health and Well-being': 'SDG3 - Good Health and Well-being',
  'Quality Education': 'SDG4 - Quality Education',
  'Gender Equality': 'SDG5 - Gender Equality',
  'Clean Water and Sanitation': 'SDG6 - Clean Water and Sanitation',
  'Affordable and Clean Energy': 'SDG7 - Affordable and Clean Energy',
  'Decent Work and Economic Growth': 'SDG8 - Decent Work and Economic Growth',
  'Industry, Innovation and Infrastructure': 'SDG9 - Industry, Innovation and Infrastructure',
  'Reduced Inequalities': 'SDG10 - Reduced Inequalities',
  'Sustainable Cities and Communities': 'SDG11 - Sustainable Cities and Communities',
  'Responsible Consumption and Production': 'SDG12 - Responsible Consumption and Production',
  'Climate Action': 'SDG13 - Climate Action',
  'Life Below Water': 'SDG14 - Life Below Water',
  'Life on Land': 'SDG15 - Life on Land',
  'Peace, Justice and Strong Institutions': 'SDG16 - Peace, Justice and Strong Institutions',
  'Partnerships for the Goals': 'SDG17 - Partnerships for the Goals',
};

/**
 * Extract display name from taxonomy value.
 * Taxonomy values are stored as "code - name" (e.g., "sdg1 - No Poverty" or "sdg1 - SDG1 - No Poverty").
 * This function returns only the name portion and applies name mapping for updated SDG names.
 */
const extractTaxonomyName = (value: string, fieldName: string): string => {
  // Only process taxonomy fields (those starting with "tag_")
  if (!fieldName.startsWith('tag_')) {
    return value;
  }

  // Check if value contains " - " separator
  const separatorIndex = value.indexOf(' - ');
  if (separatorIndex === -1) {
    return value;
  }

  // Extract the name portion (everything after the first " - ")
  let name = value.substring(separatorIndex + 3);

  // For SDG taxonomy, apply name mapping to show updated names
  if (fieldName === 'tag_sdg' && SDG_NAME_MAPPING[name]) {
    name = SDG_NAME_MAPPING[name];
  }

  return name;
};

const HeatmapTable = ({
  rowDimension,
  rowOptions,
  filteredRowValues,
  filteredColumnValues,
  columnDimension,
  columnHeaderLabel,
  gridQuery,
  setGridQuery,
  rowQueries,
  rowTitleSelections,
  rowTitleInputRefs,
  handleRowQueryChange,
  handleAddRow,
  handleRemoveRow,
  handleRowTitleSelectionClear,
  handleRowTitleSelectionCommit,
  openHeatmapFilterModal,
  isHeatmapFieldFiltered,
  filteredGridResults,
  maxCellCount,
  gridLoading,
  openCellModal,
}: HeatmapTableProps) => {
  return (
    <div className="heatmap-table-wrapper">
      {rowDimension !== 'queries' && (
        <div className="heatmap-query-row">
          <input
            id="heatmap-grid-query"
            className="heatmap-query-input"
            type="text"
            value={gridQuery}
            onChange={(event) => setGridQuery(event.target.value)}
            placeholder="Enter your search query"
          />
        </div>
      )}
      <div className="heatmap-table-scroll">
        <table className="heatmap-table">
          <colgroup>
            <col style={{ width: '40%' }} />
            {filteredColumnValues.map((column) => (
              <col key={`col-${column}`} />
            ))}
          </colgroup>
          <thead>
            <tr className="heatmap-column-label-row">
              <th className="heatmap-column-label-corner" />
              <th className="heatmap-column-label" colSpan={filteredColumnValues.length}>
                <span className="heatmap-field-label">
                  {columnHeaderLabel}
                  <button
                    type="button"
                    className={`heatmap-field-filter-button${
                      isHeatmapFieldFiltered(columnDimension) ? ' is-active' : ''
                    }`}
                    onClick={() => openHeatmapFilterModal(columnDimension, columnHeaderLabel)}
                    aria-label={`Filter ${columnHeaderLabel}`}
                    title={`Filter ${columnHeaderLabel}`}
                  >
                    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                      <path
                        d="M3 4h14L12 11v5l-4-2v-3L3 4z"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </span>
              </th>
            </tr>
            <tr>
              <th className="heatmap-row-header">
                <span className="heatmap-field-label">
                  {rowDimension === 'queries'
                    ? 'Query'
                    : rowOptions.find((option) => option.value === rowDimension)?.label}
                  {rowDimension !== 'queries' && (
                    <button
                      type="button"
                      className={`heatmap-field-filter-button${
                        isHeatmapFieldFiltered(rowDimension) ? ' is-active' : ''
                      }`}
                      onClick={() =>
                        openHeatmapFilterModal(
                          rowDimension,
                          rowOptions.find((option) => option.value === rowDimension)?.label ||
                            rowDimension
                        )
                      }
                      aria-label={`Filter ${
                        rowOptions.find((option) => option.value === rowDimension)?.label ||
                        rowDimension
                      }`}
                      title={`Filter ${
                        rowOptions.find((option) => option.value === rowDimension)?.label ||
                        rowDimension
                      }`}
                    >
                      <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                        <path
                          d="M3 4h14L12 11v5l-4-2v-3L3 4z"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  )}
                </span>
              </th>
              {filteredColumnValues.map((column) => (
                <th key={column} className="heatmap-column-header">
                  <div className="heatmap-column-header-text">{extractTaxonomyName(column, columnDimension)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRowValues.map((rowValue, rowIndex) => (
              <tr key={`heatmap-row-${rowIndex}`}>
                <td className="heatmap-query-cell">
                  {rowDimension === 'queries' || rowDimension === 'title' ? (
                    <div className="heatmap-row-controls">
                      <div className="heatmap-row-input-wrapper">
                        {rowDimension === 'title' && rowTitleSelections[rowIndex] ? (
                          <div className="heatmap-title-selection-card">
                            <span className="heatmap-title-selection-text">
                              {rowTitleSelections[rowIndex].value}
                            </span>
                            <button
                              type="button"
                              className="heatmap-title-selection-clear"
                              aria-label="Clear selected title"
                              onClick={() => handleRowTitleSelectionClear(rowIndex)}
                            >
                              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                                <path d="M4.5 4.5l7 7m0-7l-7 7" />
                              </svg>
                            </button>
                          </div>
                        ) : (
                          <input
                            ref={(node) => {
                              rowTitleInputRefs.current[rowIndex] = node;
                            }}
                            className={`heatmap-query-input${
                              rowDimension === 'title' ? ' heatmap-title-input' : ''
                            }`}
                            type="text"
                            value={rowValue}
                            onChange={(event) => handleRowQueryChange(rowIndex, event.target.value)}
                            onKeyDown={(event) => {
                              if (rowDimension !== 'title') {
                                return;
                              }
                              if (event.key !== 'Enter') {
                                return;
                              }
                              const trimmed = rowValue.trim();
                              if (!trimmed) {
                                return;
                              }
                              event.preventDefault();
                              handleRowTitleSelectionCommit(rowIndex, trimmed);
                            }}
                            placeholder={
                              rowDimension === 'title'
                                ? 'Enter a document Title ...'
                                : 'Enter your search query'
                            }
                          />
                        )}
                      </div>
                      <button type="button" onClick={handleAddRow} title="Add row">
                        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                          <path d="M8 3.5v9M3.5 8h9" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRemoveRow(rowIndex)}
                        disabled={rowQueries.length === 1}
                        title="Remove row"
                      >
                        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                          <path d="M4.5 4.5l7 7m0-7l-7 7" />
                        </svg>
                      </button>
                    </div>
                  ) : (
                    <div className="heatmap-row-label">{extractTaxonomyName(rowValue, rowDimension)}</div>
                  )}
                </td>
                {filteredColumnValues.map((column) => {
                  const rowKey = rowDimension === 'queries' ? `row-${rowIndex}` : rowValue;
                  const cellKey = buildCellKey(String(rowKey), column);
                  const cellResult = filteredGridResults[cellKey];
                  const cellCount = cellResult?.count ?? 0;
                  const intensity = maxCellCount > 0 ? cellCount / maxCellCount : 0;
                  const background = intensity
                    ? `rgba(37, 99, 235, ${0.15 + intensity * 0.65})`
                    : 'rgba(148, 163, 184, 0.08)';
                  const hasValue = cellResult !== undefined;
                  return (
                    <td
                      key={`${cellKey}-cell`}
                      className={`heatmap-cell${hasValue ? '' : ' heatmap-cell-disabled'}`}
                      style={{ backgroundColor: background }}
                      onClick={hasValue ? () => openCellModal(rowIndex, column) : undefined}
                      aria-disabled={!hasValue}
                    >
                      {gridLoading ? (hasValue ? cellCount : '…') : hasValue ? cellCount : '.'}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const HeatmapGridContent = ({
  heatmapReady,
  filteredColumnValues,
  filteredRowValues,
  rowDimension,
  rowOptions,
  columnDimension,
  columnHeaderLabel,
  gridQuery,
  setGridQuery,
  rowQueries,
  rowTitleSelections,
  rowTitleInputRefs,
  handleRowQueryChange,
  handleAddRow,
  handleRemoveRow,
  handleRowTitleSelectionClear,
  handleRowTitleSelectionCommit,
  openHeatmapFilterModal,
  isHeatmapFieldFiltered,
  filteredGridResults,
  maxCellCount,
  gridLoading,
  openCellModal,
}: Omit<HeatmapTableProps, 'filteredRowValues' | 'filteredColumnValues' | 'rowDimension' | 'rowOptions' | 'columnDimension'> & {
  heatmapReady: boolean;
  filteredColumnValues: string[];
  filteredRowValues: string[];
  rowDimension: string;
  rowOptions: { value: string; label: string }[];
  columnDimension: string;
}) => {
  if (!heatmapReady) {
    return (
      <div className="heatmap-loading">
        <RainbowText text="Loading Heatmapper..." />
      </div>
    );
  }
  if (filteredColumnValues.length === 0) {
    return (
      <div className="heatmap-empty">No column values available for the selected dimension.</div>
    );
  }
  if (filteredRowValues.length === 0) {
    return (
      <div className="heatmap-empty">No row values available for the selected dimension.</div>
    );
  }
  return (
    <HeatmapTable
      rowDimension={rowDimension}
      rowOptions={rowOptions}
      filteredRowValues={filteredRowValues}
      filteredColumnValues={filteredColumnValues}
      columnDimension={columnDimension}
      columnHeaderLabel={columnHeaderLabel}
      gridQuery={gridQuery}
      setGridQuery={setGridQuery}
      rowQueries={rowQueries}
      rowTitleSelections={rowTitleSelections}
      rowTitleInputRefs={rowTitleInputRefs}
      handleRowQueryChange={handleRowQueryChange}
      handleAddRow={handleAddRow}
      handleRemoveRow={handleRemoveRow}
      handleRowTitleSelectionClear={handleRowTitleSelectionClear}
      handleRowTitleSelectionCommit={handleRowTitleSelectionCommit}
      openHeatmapFilterModal={openHeatmapFilterModal}
      isHeatmapFieldFiltered={isHeatmapFieldFiltered}
      filteredGridResults={filteredGridResults}
      maxCellCount={maxCellCount}
      gridLoading={gridLoading}
      openCellModal={openCellModal}
    />
  );
};

const translateWithFallback = async (text: string, newLang: string, label: string) => {
  try {
    const resp = await fetch(`${API_BASE_URL}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(API_KEY ? { 'X-API-Key': API_KEY } : {}) },
      body: JSON.stringify({ text, target_language: newLang }),
    });
    if (resp.ok) {
      const data = await resp.json();
      return data.translated_text;
    }
  } catch (error) {
    console.error(`Heatmap ${label} translation failed`, error);
  }
  return text;
};

const getChunkTextForTranslation = (result: SearchResult) => {
  if (result.chunk_elements && result.chunk_elements.length > 0) {
    return result.chunk_elements
      .filter((el) => el.element_type === 'text')
      .map((el) => el.text)
      .join('\n\n');
  }
  return result.text;
};

const translateHeadings = async (headings: string[] | undefined, newLang: string) => {
  if (!headings || headings.length === 0) {
    return undefined;
  }
  const headingsText = headings.join(' > ');
  return translateWithFallback(headingsText, newLang, 'headings');
};

const getTranslatedSemanticMatches = async (
  translatedText: string,
  queryText: string,
  semanticHighlightModelConfig?: SummaryModelConfig | null
) => {
  if (!SEARCH_SEMANTIC_HIGHLIGHTS || !translatedText) {
    return undefined;
  }
  try {
    return await findSemanticMatches(
      translatedText,
      queryText,
      SEMANTIC_HIGHLIGHT_THRESHOLD,
      semanticHighlightModelConfig
    );
  } catch (error) {
    console.error('Heatmap translated highlight failed', error);
    return undefined;
  }
};

type HeatmapMetric = 'documents' | 'chunks';

const HEATMAP_URL_KEYS = {
  row: 'hm_row',
  column: 'hm_col',
  sensitivity: 'hm_sens',
  query: 'hm_q',
  rowQuery: 'hm_row_q',
  metric: 'hm_metric',
  run: 'hm_run',
} as const;

export const HeatmapTabContent: React.FC<HeatmapTabContentProps> = ({
  selectedDomain,
  loadingConfig,
  facetsDataSource,
  filtersExpanded,
  activeFiltersCount,
  onToggleFiltersExpanded,
  onClearFilters,
  facets,
  filters,
  selectedFilters,
  collapsedFilters,
  expandedFilterLists,
  filterSearchTerms,
  titleSearchResults,
  facetSearchResults,
  onRemoveFilter,
  onToggleFilter,
  onFilterSearchTermChange,
  onToggleFilterListExpansion,
  onFilterValuesChange,
  searchModel,
  searchDenseWeight,
  onSearchDenseWeightChange,
  keywordBoostShortQueries,
  onKeywordBoostChange,
  semanticHighlighting,
  onSemanticHighlightingChange,
  semanticHighlightModelConfig,
  minScore,
  maxScore,
  onMinScoreChange,
  rerankEnabled,
  onRerankToggle,
  recencyBoostEnabled,
  onRecencyBoostToggle,
  recencyWeight,
  onRecencyWeightChange,
  recencyScaleDays,
  onRecencyScaleDaysChange,
  rerankModel,
  minChunkSize,
  onMinChunkSizeChange,
  sectionTypes,
  onSectionTypesChange,
  dataSource,
  selectedDoc,
  onResultClick,
  onOpenMetadata,
  onLanguageChange,
  onRequestHighlight,
}) => {
  const [rowQueries, setRowQueries] = useState<string[]>(['']);
  const [columnDimension, setColumnDimension] = useState<string>('published_year');
  const [rowDimension, setRowDimension] = useState<string>('document_type');
  const [similarityCutoff, setSimilarityCutoff] = useState<number>(0.5);
  const [heatmapMetric, setHeatmapMetric] = useState<HeatmapMetric>('documents');
  const [gridQuery, setGridQuery] = useState<string>('');
  const [gridResults, setGridResults] = useState<RawCellResults>({});
  const [gridLoading, setGridLoading] = useState<boolean>(false);
  const [gridError, setGridError] = useState<string | null>(null);
  const [heatmapSelectedFilters, setHeatmapSelectedFilters] = useState<Record<string, string[]>>({});
  const [heatmapFilterModal, setHeatmapFilterModal] = useState<HeatmapFilterModalState | null>(null);
  const [heatmapFilterSearchTerms, setHeatmapFilterSearchTerms] = useState<Record<string, string>>({});
  const [heatmapCollapsedFilters, setHeatmapCollapsedFilters] = useState<Set<string>>(new Set());
  const [heatmapExpandedFilterLists, setHeatmapExpandedFilterLists] = useState<Set<string>>(new Set());
  const [heatmapFacetSearchResults, setHeatmapFacetSearchResults] = useState<Record<string, FacetValue[]>>({});
  const [heatmapTitleSearchResults, setHeatmapTitleSearchResults] = useState<FacetValue[]>([]);
  const heatmapTitleSearchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heatmapFacetSearchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [rowTitleSearchResults, setRowTitleSearchResults] = useState<Record<number, FacetValue[]>>({});
  const [rowTitleSelections, setRowTitleSelections] = useState<Record<number, FacetValue>>({});
  const rowTitleSearchTimeoutsRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});
  const rowTitleInputRefs = useRef<Record<number, HTMLInputElement | null>>({});
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  const [activeCell, setActiveCell] = useState<{
    rowIndex: number;
    columnValue: string;
    query: string;
  } | null>(null);
  const [heatmapReady, setHeatmapReady] = useState<boolean>(false);
  const processingHighlightsRef = useRef<Set<string>>(new Set());
  const heatmapUrlInitRef = useRef(false);
  const heatmapAutoRunRef = useRef(false);

  // Heatmap filters are now completely isolated from global filters
  // No syncing needed

  const columnOptions = useMemo(() => {
    if (!facets) return [];
    return Object.entries(facets.filter_fields).map(([value, label]) => ({
      value,
      label,
    }));
  }, [facets]);

  useEffect(() => {
    if (columnOptions.length === 0) {
      return;
    }
    const hasSelected = columnOptions.some((option) => option.value === columnDimension);
    if (!hasSelected) {
      setColumnDimension(columnOptions[0].value);
    }
  }, [columnDimension, columnOptions]);

  const rowOptions = useMemo(() => {
    if (!facets) {
      return [
        { value: 'queries', label: 'Search query' },
        { value: 'title', label: 'Report Title' }
      ];
    }
    const facetEntries = Object.entries(facets.filter_fields).filter(([value]) => value !== 'title');
    return [
      { value: 'queries', label: 'Search query' },
      { value: 'title', label: 'Report Title' },
      ...facetEntries.map(([value, label]) => ({
        value,
        label,
      })),
    ];
  }, [facets]);

  useEffect(() => {
    if (rowOptions.length === 0) {
      return;
    }
    const hasSelected = rowOptions.some((option) => option.value === rowDimension);
    if (!hasSelected) {
      setRowDimension('document_type');
    }
  }, [rowDimension, rowOptions]);

  const columnValues = useMemo(() => {
    if (!facets || !columnDimension) return [];
    const values = facets.facets[columnDimension] || [];
    const sorted = [...values].sort((a, b) => {
      const aValue = a.value ?? '';
      const bValue = b.value ?? '';
      const aNumber = Number(aValue);
      const bNumber = Number(bValue);
      const bothNumeric = !Number.isNaN(aNumber) && !Number.isNaN(bNumber);
      if (bothNumeric) {
        return aNumber - bNumber;
      }
      return String(aValue).localeCompare(String(bValue));
    });
    return sorted
      .map((item) => item.value)
      .filter((value): value is string => value !== undefined && value !== null);
  }, [columnDimension, facets]);

  const rowValues = useMemo(() => {
    if (rowDimension === 'queries' || rowDimension === 'title') {
      return rowQueries;
    }
    if (!facets || !rowDimension) return [];
    const values = facets.facets[rowDimension] || [];
    const sorted = [...values].sort((a, b) => {
      const aValue = a.value ?? '';
      const bValue = b.value ?? '';
      const aNumber = Number(aValue);
      const bNumber = Number(bValue);
      const bothNumeric = !Number.isNaN(aNumber) && !Number.isNaN(bNumber);
      if (bothNumeric) {
        return aNumber - bNumber;
      }
      return String(aValue).localeCompare(String(bValue));
    });
    return sorted
      .map((item) => item.value)
      .filter((value): value is string => value !== undefined && value !== null);
  }, [facets, rowDimension, rowQueries]);

  const getFieldValues = useCallback(
    (field: string) => {
      if (field === columnDimension) {
        return columnValues;
      }
      if (field === rowDimension) {
        return rowValues;
      }
      return [];
    },
    [columnDimension, columnValues, rowDimension, rowValues]
  );

  const applyHeatmapFieldFilter = useCallback(
    (values: string[], field: string) => {
      const selectedValues = heatmapSelectedFilters[field];
      if (!selectedValues) {
        return values;
      }
      if (selectedValues.length === 0) {
        return [];
      }
      if (selectedValues.length === values.length) {
        return values;
      }
      const allowed = new Set(selectedValues);
      return values.filter((value) => allowed.has(value));
    },
    [heatmapSelectedFilters]
  );

  const filteredColumnValues = useMemo(() => {
    return applyHeatmapFieldFilter(columnValues, columnDimension);
  }, [applyHeatmapFieldFilter, columnDimension, columnValues]);

  const filteredRowValues = useMemo(() => {
    if (rowDimension === 'queries') {
      return rowValues;
    }
    return applyHeatmapFieldFilter(rowValues, rowDimension);
  }, [applyHeatmapFieldFilter, rowDimension, rowValues]);

  const hasGridSearchQuery = useMemo(() => {
    if (rowDimension === 'queries' || rowDimension === 'title') {
      return rowQueries.some((query) => query.trim().length > 0);
    }
    // Allow blank queries for non-query dimensions (count by dimensions only)
    return true;
  }, [rowDimension, rowQueries]);

  const performRowTitleSearch = useCallback(
    (rowIndex: number, query: string) => {
      const trimmed = query.trim();
      const normalizedQuery = trimmed.toLowerCase();
      if (rowTitleSearchTimeoutsRef.current[rowIndex]) {
        clearTimeout(rowTitleSearchTimeoutsRef.current[rowIndex]);
      }
      if (trimmed.length < 2) {
        setRowTitleSearchResults((prev) => ({ ...prev, [rowIndex]: [] }));
        return;
      }
      rowTitleSearchTimeoutsRef.current[rowIndex] = setTimeout(async () => {
        try {
          const params = new URLSearchParams();
          params.append('q', trimmed);
          params.append('limit', '25');
          params.append('data_source', dataSource);
          if (searchModel) {
            params.append('model', searchModel);
          }
          const response = await axios.get<any[]>(`${API_BASE_URL}/search/titles?${params}`);
          const data = response.data as any[];
          const facetsResults: FacetValue[] = data.map((item: any) => ({
            value: item.title,
            count: 1,
            organization: item.organization,
            published_year: item.year ? String(item.year) : undefined,
          }));
          const sortedResults = [...facetsResults].sort((a, b) => {
            const aMatch = a.value.toLowerCase().includes(normalizedQuery);
            const bMatch = b.value.toLowerCase().includes(normalizedQuery);
            if (aMatch === bMatch) return 0;
            return aMatch ? -1 : 1;
          });
          setRowTitleSearchResults((prev) => ({
            ...prev,
            [rowIndex]: sortedResults.slice(0, 5),
          }));
        } catch (error) {
          console.error('Row title search failed:', error);
          setRowTitleSearchResults((prev) => ({ ...prev, [rowIndex]: [] }));
        }
      }, 300);
    },
    [dataSource, searchModel]
  );

  const getTitleSuggestionPosition = useCallback((rowIndex: number) => {
    const input = rowTitleInputRefs.current[rowIndex];
    if (!input) {
      return null;
    }
    const rect = input.getBoundingClientRect();
    return {
      top: rect.bottom + 6,
      left: rect.left,
      width: rect.width,
    };
  }, []);

  const openHeatmapFilterModal = useCallback(
    (field: string, label: string) => {
      const values = getFieldValues(field);
      const currentSelected = heatmapSelectedFilters[field];
      const initialSelectedValues = currentSelected ? [...currentSelected] : [...values];
      setHeatmapCollapsedFilters(new Set());
      setHeatmapExpandedFilterLists(new Set());
      setHeatmapFilterSearchTerms((prev) => ({ ...prev, [field]: '' }));
      setHeatmapSelectedFilters((prev) => {
        if (Object.prototype.hasOwnProperty.call(prev, field)) {
          return prev;
        }
        return {
          ...prev,
          [field]: values,
        };
      });
      setHeatmapFilterModal({ field, label, initialSelectedValues });
    },
    [filters, getFieldValues, heatmapSelectedFilters]
  );

  const closeHeatmapFilterModal = useCallback(() => {
    setHeatmapFilterModal(null);
  }, []);

  const cancelHeatmapFilterModal = useCallback(() => {
    if (!heatmapFilterModal) {
      return;
    }
    const { field, initialSelectedValues } = heatmapFilterModal;
    setHeatmapSelectedFilters((prev) => ({ ...prev, [field]: initialSelectedValues }));
    closeHeatmapFilterModal();
  }, [closeHeatmapFilterModal, heatmapFilterModal]);

  const toggleHeatmapFilter = useCallback((field: string) => {
    setHeatmapCollapsedFilters((prev) => {
      const next = new Set(prev);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
  }, []);

  const toggleHeatmapFilterListExpansion = useCallback((field: string) => {
    setHeatmapExpandedFilterLists((prev) => {
      const next = new Set(prev);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
  }, []);

  const performHeatmapFacetSearch = useCallback(
    (field: string, query: string) => {
      if (heatmapFacetSearchTimeoutRef.current) {
        clearTimeout(heatmapFacetSearchTimeoutRef.current);
      }
      if (!query || query.trim().length < 2) {
        setHeatmapFacetSearchResults((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
        return;
      }
      heatmapFacetSearchTimeoutRef.current = setTimeout(async () => {
        try {
          const params = new URLSearchParams();
          params.append('field', field);
          params.append('q', query.trim());
          params.append('limit', '100');
          params.append('data_source', dataSource);
          const response = await axios.get<any[]>(`${API_BASE_URL}/search/facet-values?${params}`);
          const data = response.data as any[];
          const facetsResults: FacetValue[] = data.map((item: any) => ({
            value: item.value,
            count: item.count,
          }));
          setHeatmapFacetSearchResults((prev) => ({
            ...prev,
            [field]: facetsResults,
          }));
        } catch (error) {
          console.error(`Facet search failed for ${field}:`, error);
        }
      }, 300);
    },
    [dataSource]
  );

  const handleHeatmapFilterSearchTermChange = useCallback(
    (coreField: string, value: string) => {
      setHeatmapFilterSearchTerms((prev) => ({ ...prev, [coreField]: value }));
      if (coreField !== 'title') {
        performHeatmapFacetSearch(coreField, value);
      }
    },
    [performHeatmapFacetSearch]
  );

  useEffect(() => {
    if (heatmapFilterModal?.field !== 'title') {
      if (heatmapTitleSearchTimeoutRef.current) {
        clearTimeout(heatmapTitleSearchTimeoutRef.current);
      }
      setHeatmapTitleSearchResults([]);
      return;
    }
    const titleQuery = heatmapFilterSearchTerms['title'];
    if (heatmapTitleSearchTimeoutRef.current) {
      clearTimeout(heatmapTitleSearchTimeoutRef.current);
    }
    if (!titleQuery || titleQuery.trim().length < 2) {
      setHeatmapTitleSearchResults([]);
      return;
    }
    heatmapTitleSearchTimeoutRef.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        params.append('q', titleQuery.trim());
        params.append('limit', '50');
        params.append('data_source', dataSource);
        if (searchModel) {
          params.append('model', searchModel);
        }
        const response = await axios.get<any[]>(`${API_BASE_URL}/search/titles?${params}`);
        const data = response.data as any[];
        const facetsResults: FacetValue[] = data.map((item: any) => ({
          value: item.title,
          count: 1,
          organization: item.organization,
          published_year: item.year ? String(item.year) : undefined,
        }));
        setHeatmapTitleSearchResults(facetsResults);
      } catch (error) {
        console.error('Title search failed:', error);
      }
    }, 300);

    return () => {
      if (heatmapTitleSearchTimeoutRef.current) {
        clearTimeout(heatmapTitleSearchTimeoutRef.current);
      }
    };
  }, [dataSource, heatmapFilterModal?.field, heatmapFilterSearchTerms['title'], searchModel]);

  const handleHeatmapFilterValuesChange = useCallback(
    (coreField: string, nextValues: string[]) => {
      setHeatmapSelectedFilters((prev) => ({ ...prev, [coreField]: nextValues }));
    },
    []
  );

  const handleHeatmapRemoveFilter = useCallback((coreField: string, value: string) => {
    setHeatmapSelectedFilters((prev) => {
      const currentValues = prev[coreField] || [];
      const nextValues = currentValues.filter((v) => v !== value);
      return { ...prev, [coreField]: nextValues };
    });
  }, []);

  const clearHeatmapFilterField = useCallback((field: string) => {
    setHeatmapSelectedFilters((prev) => ({ ...prev, [field]: [] }));
  }, []);

  const isHeatmapFieldFiltered = useCallback(
    (field: string) => {
      const selected = heatmapSelectedFilters[field];
      if (!selected) {
        return false;
      }
      const allValues = getFieldValues(field);
      if (selected.length === 0) {
        return true;
      }
      return selected.length !== allValues.length;
    },
    [getFieldValues, heatmapSelectedFilters]
  );

  const updateHeatmapURL = useCallback(
    (options?: { run?: boolean }) => {
      const url = new URL(window.location.href);
      const params = url.searchParams;

      params.set(HEATMAP_URL_KEYS.row, rowDimension);
      params.set(HEATMAP_URL_KEYS.column, columnDimension);
      params.set(HEATMAP_URL_KEYS.metric, heatmapMetric);
      params.set(HEATMAP_URL_KEYS.sensitivity, similarityCutoff.toString());

      params.delete(HEATMAP_URL_KEYS.query);
      params.delete(HEATMAP_URL_KEYS.rowQuery);
      if (rowDimension === 'queries') {
        rowQueries
          .map((query) => query.trim())
          .filter((query) => query.length > 0)
          .forEach((query) => params.append(HEATMAP_URL_KEYS.rowQuery, query));
      } else if (gridQuery.trim()) {
        params.set(HEATMAP_URL_KEYS.query, gridQuery.trim());
      }

      for (const [field, values] of Object.entries(heatmapSelectedFilters)) {
        if (values && values.length > 0) {
          params.set(field, values.join(','));
        } else {
          params.delete(field);
        }
      }

      if (options?.run) {
        params.set(HEATMAP_URL_KEYS.run, 'true');
      } else {
        params.delete(HEATMAP_URL_KEYS.run);
      }

      url.search = params.toString();
      window.history.replaceState(null, '', url.toString());
    },
    [columnDimension, heatmapSelectedFilters, gridQuery, heatmapMetric, rowDimension, rowQueries, similarityCutoff]
  );


  const applyHeatmapUrlParams = (params: URLSearchParams) => {
    const urlRow = params.get(HEATMAP_URL_KEYS.row);
    const urlColumn = params.get(HEATMAP_URL_KEYS.column);
    const urlSensitivity = params.get(HEATMAP_URL_KEYS.sensitivity);
    const urlQuery = params.get(HEATMAP_URL_KEYS.query);
    const urlRowQueries = params.getAll(HEATMAP_URL_KEYS.rowQuery);

    if (urlRow && rowOptions.some((option) => option.value === urlRow)) {
      setRowDimension(urlRow);
    }
    if (urlColumn && columnOptions.some((option) => option.value === urlColumn)) {
      setColumnDimension(urlColumn);
    }
    const urlMetric = params.get(HEATMAP_URL_KEYS.metric);
    if (urlMetric === 'documents' || urlMetric === 'chunks') {
      setHeatmapMetric(urlMetric);
    }
    const parsedSensitivity = urlSensitivity ? Number(urlSensitivity) : NaN;
    if (!Number.isNaN(parsedSensitivity)) {
      setSimilarityCutoff(parsedSensitivity);
    }
    if (urlRow === 'queries' && urlRowQueries.length > 0) {
      setRowQueries(urlRowQueries);
    } else if (urlRow !== 'queries' && urlQuery) {
      setGridQuery(urlQuery);
    }

    // Load filter parameters from URL into heatmap filters
    if (facets) {
      const urlFilters: Record<string, string[]> = {};
      const allFilterFields = Object.keys(facets.filter_fields);

      allFilterFields.forEach((field) => {
        const urlValue = params.get(field);
        if (urlValue) {
          const values = urlValue.split(',').map((v) => v.trim()).filter((v) => v.length > 0);
          if (values.length > 0) {
            urlFilters[field] = values;
          }
        }
      });

      if (Object.keys(urlFilters).length > 0) {
        setHeatmapSelectedFilters(urlFilters);
      }
    }

    heatmapAutoRunRef.current = params.get(HEATMAP_URL_KEYS.run) === 'true';
    heatmapUrlInitRef.current = true;
  };

  useEffect(() => {
    if (heatmapUrlInitRef.current || !facets) {
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const urlDataset = params.get('dataset');
    if (urlDataset && (loadingConfig || selectedDomain !== urlDataset)) {
      return;
    }
    if (facetsDataSource && facetsDataSource !== dataSource) {
      return;
    }

    applyHeatmapUrlParams(params);
  }, [
    columnOptions,
    dataSource,
    facets,
    facetsDataSource,
    loadingConfig,
    rowOptions,
    selectedDomain,
  ]);

  useEffect(() => {
    if (!heatmapUrlInitRef.current) {
      return;
    }
    updateHeatmapURL({ run: false });
  }, [
    columnDimension,
    gridQuery,
    hasGridSearchQuery,
    heatmapMetric,
    rowDimension,
    rowQueries,
    similarityCutoff,
    updateHeatmapURL,
  ]);

  const getActiveCellKey = useCallback(() => {
    if (!activeCell) return null;
    const rowKey = rowDimension === 'queries'
      ? `row-${activeCell.rowIndex}`
      : (filteredRowValues[activeCell.rowIndex] || '');
    return buildCellKey(String(rowKey), activeCell.columnValue);
  }, [activeCell, filteredRowValues, rowDimension]);

  useEffect(() => {
    setGridResults({});
    setActiveCell(null);
  }, [
    columnDimension,
    filteredColumnValues.length,
    filteredRowValues.length,
    heatmapSelectedFilters,
    rowDimension,
    rowQueries,
  ]);

  useEffect(() => {
    if (rowDimension !== 'title') {
      setRowTitleSearchResults({});
      Object.values(rowTitleSearchTimeoutsRef.current).forEach((timeoutId) => {
        clearTimeout(timeoutId);
      });
      rowTitleSearchTimeoutsRef.current = {};
      return;
    }
    rowQueries.forEach((query, index) => {
      if (query.trim()) {
        performRowTitleSearch(index, query);
      }
    });
  }, [performRowTitleSearch, rowDimension, rowQueries]);

  useEffect(() => {
    setHeatmapReady(false);
  }, [dataSource]);

  useEffect(() => {
    if (facets && (!facetsDataSource || facetsDataSource === dataSource)) {
      setHeatmapReady(true);
    }
  }, [dataSource, facets, facetsDataSource]);

  const filteredGridResults = useMemo<Record<string, CellResult>>(() => {
    const nextResults: Record<string, CellResult> = {};
    for (const [cellKey, results] of Object.entries(gridResults)) {
      // score === 0 means no similarity was computed (filter-only scroll), always include
      const filtered = results.filter((result) => result.score === 0 || result.score >= similarityCutoff);
      const count =
        heatmapMetric === 'documents'
          ? new Set(filtered.map((result) => result.doc_id)).size
          : filtered.length;
      nextResults[cellKey] = { results: filtered, count };
    }
    return nextResults;
  }, [gridResults, heatmapMetric, similarityCutoff]);

  const hasCompletedGridSearch = useMemo(() => {
    return !gridLoading && Object.keys(gridResults).length > 0;
  }, [gridLoading, gridResults]);

  const columnHeaderLabel = useMemo(() => {
    return (
      columnOptions.find((option) => option.value === columnDimension)?.label ||
      columnDimension
    );
  }, [columnDimension, columnOptions]);

  const sortFacetValues = useCallback((values: FacetValue[], selectedValues: string[]) => {
    if (selectedValues.length === 0) {
      return values;
    }
    const selectedSet = new Set(selectedValues);
    return [...values].sort((a, b) => {
      const aSelected = selectedSet.has(a.value);
      const bSelected = selectedSet.has(b.value);
      if (aSelected === bSelected) {
        return 0;
      }
      return aSelected ? -1 : 1;
    });
  }, []);

  const modalFieldValues = useMemo(() => {
    if (!heatmapFilterModal) {
      return [];
    }
    return getFieldValues(heatmapFilterModal.field);
  }, [getFieldValues, heatmapFilterModal]);

  const modalSelectedValues = useMemo(() => {
    if (!heatmapFilterModal) {
      return [];
    }
    return heatmapSelectedFilters[heatmapFilterModal.field] || [];
  }, [heatmapFilterModal, heatmapSelectedFilters]);

  const heatmapModalFacets = useMemo(() => {
    if (!heatmapFilterModal || !facets) {
      return null;
    }
    const baseValues = facets.facets[heatmapFilterModal.field] || [];
    // Transform taxonomy values to display clean names
    const transformedValues = baseValues.map((facetValue) => ({
      ...facetValue,
      value: extractTaxonomyName(facetValue.value, heatmapFilterModal.field),
    }));
    const orderedValues = sortFacetValues(transformedValues, modalSelectedValues);
    return {
      filter_fields: { [heatmapFilterModal.field]: heatmapFilterModal.label },
      facets: { [heatmapFilterModal.field]: orderedValues },
    };
  }, [facets, heatmapFilterModal, modalSelectedValues, sortFacetValues]);

  const orderedHeatmapFacetSearchResults = useMemo(() => {
    if (!heatmapFilterModal) {
      return heatmapFacetSearchResults;
    }
    const field = heatmapFilterModal.field;
    const results = heatmapFacetSearchResults[field];
    if (!results) {
      return heatmapFacetSearchResults;
    }
    // Transform taxonomy values to display clean names
    const transformedResults = results.map((facetValue) => ({
      ...facetValue,
      value: extractTaxonomyName(facetValue.value, field),
    }));
    return {
      ...heatmapFacetSearchResults,
      [field]: sortFacetValues(transformedResults, modalSelectedValues),
    };
  }, [heatmapFacetSearchResults, heatmapFilterModal, modalSelectedValues, sortFacetValues]);

  const orderedHeatmapTitleSearchResults = useMemo(() => {
    if (!heatmapFilterModal || heatmapFilterModal.field !== 'title') {
      return heatmapTitleSearchResults;
    }
    return sortFacetValues(heatmapTitleSearchResults, modalSelectedValues);
  }, [heatmapFilterModal, heatmapTitleSearchResults, modalSelectedValues, sortFacetValues]);

  useEffect(() => {
    if (!selectAllRef.current || !heatmapFilterModal) {
      return;
    }
    const hasValues = modalFieldValues.length > 0;
    const isAllSelected = hasValues && modalSelectedValues.length === modalFieldValues.length;
    const isNoneSelected = modalSelectedValues.length === 0;
    selectAllRef.current.indeterminate = !isAllSelected && !isNoneSelected;
  }, [heatmapFilterModal, modalFieldValues.length, modalSelectedValues.length]);

  const toggleHeatmapSelectAll = useCallback(() => {
    if (!heatmapFilterModal) {
      return;
    }
    const field = heatmapFilterModal.field;
    const values = modalFieldValues;
    setHeatmapSelectedFilters((prev) => {
      const current = prev[field] || [];
      const isAllSelected = values.length > 0 && current.length === values.length;
      return { ...prev, [field]: isAllSelected ? [] : values };
    });
  }, [heatmapFilterModal, modalFieldValues]);

  const handleDownloadExcel = useCallback(() => {
    if (filteredColumnValues.length === 0 || filteredRowValues.length === 0) {
      return;
    }

    const rowLabel =
      rowDimension === 'queries'
        ? 'Query'
        : rowOptions.find((option) => option.value === rowDimension)?.label || rowDimension;
    const columnLabel =
      columnOptions.find((option) => option.value === columnDimension)?.label || columnDimension;

    const headerRow = [
      `${rowLabel} \\ ${columnLabel}`,
      ...filteredColumnValues.map((col) => extractTaxonomyName(col, columnDimension))
    ];
    const rows = filteredRowValues.map((rowValue, rowIndex) => {
      const rowKey = rowDimension === 'queries' ? `row-${rowIndex}` : rowValue;
      const label =
        rowDimension === 'queries' || rowDimension === 'title'
          ? rowValue.trim() || `Row ${rowIndex + 1}`
          : extractTaxonomyName(rowValue, rowDimension);

      const cellValues = filteredColumnValues.map((columnValue) => {
        const cellKey = buildCellKey(String(rowKey), columnValue);
        const cellResults = filteredGridResults[cellKey]?.results || [];
        return formatHeatmapCellValue(cellResults);
      });

      return [label, ...cellValues];
    });

    const worksheet = XLSX.utils.aoa_to_sheet([headerRow, ...rows]);
    applyHeatmapHeaderStyles(worksheet);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Heatmap');

    const fileName = `heatmap-${rowDimension}-by-${columnDimension}.xlsx`;
    XLSX.writeFile(workbook, fileName);
  }, [
    columnDimension,
    columnOptions,
    filteredColumnValues,
    filteredGridResults,
    rowDimension,
    rowOptions,
    filteredRowValues,
  ]);

  const scoreBounds = useMemo(() => {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    let hasScores = false;

    Object.values(gridResults).forEach((results) => {
      results.forEach((result) => {
        // score === 0 means filter-only (no similarity), skip for bounds
        if (!Number.isFinite(result.score) || result.score === 0) {
          return;
        }
        hasScores = true;
        min = Math.min(min, result.score);
        max = Math.max(max, result.score);
      });
    });

    if (!hasScores || !Number.isFinite(min) || !Number.isFinite(max)) {
      return { min: 0, max: 1, hasScores: false };
    }

    const boundedMin = Math.max(0, min);
    const boundedMax = Math.max(boundedMin, max);
    if (!Number.isFinite(boundedMin) || !Number.isFinite(boundedMax)) {
      return { min: 0, max: 1, hasScores: false };
    }
    if (boundedMin === boundedMax) {
      const padding = Math.max(0.01, boundedMin * 0.05);
      return {
        min: Math.max(0, boundedMin - padding),
        max: boundedMax + padding,
        hasScores: true,
      };
    }
    return { min: boundedMin, max: boundedMax, hasScores: true };
  }, [gridResults]);

  useEffect(() => {
    if (!scoreBounds.hasScores) {
      return;
    }
    const midpoint = scoreBounds.min + (scoreBounds.max - scoreBounds.min) / 2;
    setSimilarityCutoff(midpoint);
  }, [scoreBounds]);

  const maxCellCount = useMemo(() => {
    return Object.values(filteredGridResults).reduce((max, cell) => Math.max(max, cell.count), 0);
  }, [filteredGridResults]);

  const handleRowQueryChange = (rowIndex: number, value: string) => {
    setRowQueries((prev) => prev.map((row, index) => (index === rowIndex ? value : row)));
    if (rowDimension === 'title') {
      setRowTitleSelections((prev) => {
        if (!prev[rowIndex]) return prev;
        const next = { ...prev };
        delete next[rowIndex];
        return next;
      });
      performRowTitleSearch(rowIndex, value);
    }
  };

  const handleRowTitleSelectionClear = useCallback((rowIndex: number) => {
    setRowQueries((prev) => prev.map((row, index) => (index === rowIndex ? '' : row)));
    setRowTitleSelections((prev) => {
      const next = { ...prev };
      delete next[rowIndex];
      return next;
    });
  }, []);

  const handleRowTitleSelectionCommit = useCallback((rowIndex: number, value: string) => {
    setRowTitleSelections((prev) => ({
      ...prev,
      [rowIndex]: {
        value,
        count: 1,
      },
    }));
    setRowTitleSearchResults((prev) => ({ ...prev, [rowIndex]: [] }));
  }, []);

  const handleAddRow = () => {
    setRowQueries((prev) => [...prev, '']);
  };

  const handleRemoveRow = (rowIndex: number) => {
    setRowQueries((prev) => prev.filter((_, index) => index !== rowIndex));
    setRowTitleSearchResults((prev) => {
      const next = { ...prev };
      delete next[rowIndex];
      return next;
    });
    setRowTitleSelections((prev) => {
      const next = { ...prev };
      delete next[rowIndex];
      return next;
    });
    if (rowTitleSearchTimeoutsRef.current[rowIndex]) {
      clearTimeout(rowTitleSearchTimeoutsRef.current[rowIndex]);
      delete rowTitleSearchTimeoutsRef.current[rowIndex];
    }
  };

  const buildCellQuery = useCallback(
    (rowValue: string, _columnValue: string, _rowIndex: number) => {
      const baseQuery = rowDimension === 'queries' ? rowValue : gridQuery;
      return baseQuery.trim();
    },
    [gridQuery, rowDimension]
  );

  const executeGridSearch = useCallback(async () => {
    if (filteredColumnValues.length === 0) {
      setGridResults({});
      return;
    }
    updateHeatmapURL({ run: true });
    setGridLoading(true);
    setGridError(null);
    setGridResults({});
    const tasks: Array<() => Promise<void>> = [];
    let failedRequests = 0;
    const excludedFields = buildExcludedFilterFields(rowDimension, columnDimension);
    const filterEntries = Object.entries(heatmapSelectedFilters)
      .filter(([field]) => !excludedFields.has(field))
      .map(([field, values]) => [field, values.length > 0 ? values.join(',') : null] as [string, string | null]);

    filteredRowValues.forEach((rowValue, rowIndex) => {
      const rowKey = rowDimension === 'queries' ? `row-${rowIndex}` : rowValue;
      filteredColumnValues.forEach((columnValue) => {
        const cellKey = buildCellKey(String(rowKey), columnValue);
        const cellQuery = buildCellQuery(rowValue, columnValue, rowIndex);
        // For 'queries' dimension, skip cells with no query text
        if (rowDimension === 'queries' && !cellQuery) {
          setGridResults((prev) => ({ ...prev, [cellKey]: [] }));
          return;
        }

        const params = buildSearchParams({
          cellQuery,
          rowDimension,
          rowValue,
          columnDimension,
          columnValue,
          filterEntries,
          searchDenseWeight,
          rerankEnabled,
          recencyBoostEnabled,
          recencyWeight,
          recencyScaleDays,
          sectionTypes,
          keywordBoostShortQueries,
          minChunkSize,
          rerankModel,
          searchModel,
          dataSource,
        });

        tasks.push(async () => {
          try {
            const response = await axios.get<SearchResponse>(`${API_BASE_URL}/search?${params}`);
            const data = response.data as SearchResponse;
            setGridResults((prev) => ({ ...prev, [cellKey]: data.results }));
          } catch (error) {
            failedRequests += 1;
            setGridResults((prev) => ({ ...prev, [cellKey]: [] }));
          }
        });
      });
    });

    try {
      await runTasksInBatches(tasks);
      if (failedRequests > 0) {
        setGridError('Some grid cells failed to load.');
      }
    } catch (error) {
      console.error('Heatmap grid search failed:', error);
      setGridError('Grid search failed. Please try again.');
    } finally {
      setGridLoading(false);
    }
  }, [
    columnDimension,
    buildCellQuery,
    dataSource,
    heatmapSelectedFilters,
    filteredColumnValues,
    filteredRowValues,
    gridQuery,
    keywordBoostShortQueries,
    minChunkSize,
    recencyBoostEnabled,
    recencyScaleDays,
    recencyWeight,
    rerankEnabled,
    rerankModel,
    rowDimension,
    searchDenseWeight,
    searchModel,
    sectionTypes,
    updateHeatmapURL,
  ]);

  useEffect(() => {
    if (!heatmapAutoRunRef.current) {
      return;
    }
    if (
      !heatmapReady ||
      gridLoading ||
      filteredColumnValues.length === 0 ||
      filteredRowValues.length === 0
    ) {
      return;
    }
    if (!hasGridSearchQuery) {
      return;
    }
    heatmapAutoRunRef.current = false;
    executeGridSearch();
  }, [
    filteredColumnValues.length,
    executeGridSearch,
    gridLoading,
    hasGridSearchQuery,
    heatmapReady,
    filteredRowValues.length,
  ]);


  const openCellModal = (rowIndex: number, columnValue: string) => {
    const rowValue = filteredRowValues[rowIndex] || '';
    const rowKey = rowDimension === 'queries' ? `row-${rowIndex}` : rowValue;
    const query = buildCellQuery(rowValue, columnValue, rowIndex);
    setActiveCell({ rowIndex, columnValue, query: query || '' });
  };

  const closeCellModal = () => {
    setActiveCell(null);
  };

  const activeCellResults = useMemo(() => {
    if (!activeCell) return [];
    const rowKey = rowDimension === 'queries'
      ? `row-${activeCell.rowIndex}`
      : (filteredRowValues[activeCell.rowIndex] || '');
    const cellKey = buildCellKey(String(rowKey), activeCell.columnValue);
    return filteredGridResults[cellKey]?.results || [];
  }, [activeCell, filteredGridResults, filteredRowValues, rowDimension]);

  const uniqueActiveCellDocuments = useMemo(() => {
    if (!activeCellResults || activeCellResults.length === 0) return [];

    // Count results per document
    const docCounts = new Map<string, number>();
    activeCellResults.forEach((result) => {
      docCounts.set(result.doc_id, (docCounts.get(result.doc_id) || 0) + 1);
    });

    // Get unique documents
    const seenDocs = new Set<string>();
    const uniqueDocs: SearchResult[] = [];
    activeCellResults.forEach((result) => {
      if (!seenDocs.has(result.doc_id)) {
        seenDocs.add(result.doc_id);
        uniqueDocs.push(result);
      }
    });

    // Sort by result count (descending)
    uniqueDocs.sort((a, b) => {
      const countA = docCounts.get(a.doc_id) || 0;
      const countB = docCounts.get(b.doc_id) || 0;
      return countB - countA;
    });

    return uniqueDocs;
  }, [activeCellResults]);

  const [filteredDocId, setFilteredDocId] = useState<string | null>(null);

  const displayedCellResults = useMemo(() => {
    if (!filteredDocId) return activeCellResults;
    return activeCellResults.filter(result => result.doc_id === filteredDocId);
  }, [activeCellResults, filteredDocId]);

  const filteredDocTitle = useMemo(() => {
    if (!filteredDocId) return null;
    const doc = uniqueActiveCellDocuments.find(d => d.doc_id === filteredDocId);
    return doc?.title || 'Unknown Document';
  }, [filteredDocId, uniqueActiveCellDocuments]);

  // Reset filter when cell changes
  useEffect(() => {
    setFilteredDocId(null);
  }, [activeCell]);

  const handleHeatmapHighlight = useCallback(
    async (chunkId: string, text: string) => {
      if (!activeCell || !semanticHighlighting || !SEARCH_SEMANTIC_HIGHLIGHTS) {
        return;
      }
      if (processingHighlightsRef.current.has(chunkId)) {
        return;
      }
      const queryText = activeCell.query?.trim();
      if (!queryText) {
        return;
      }

      processingHighlightsRef.current.add(chunkId);
      try {
        const semanticMatches = await findSemanticMatches(
          text,
          queryText,
          SEMANTIC_HIGHLIGHT_THRESHOLD,
          semanticHighlightModelConfig
        );
        const rowKey = rowDimension === 'queries'
          ? `row-${activeCell.rowIndex}`
          : (filteredRowValues[activeCell.rowIndex] || '');
        const cellKey = buildCellKey(String(rowKey), activeCell.columnValue);
        setGridResults((prev) => {
          const cellResults = prev[cellKey];
          if (!cellResults) {
            return prev;
          }
          const updatedResults = cellResults.map((result) => {
            if (result.chunk_id !== chunkId) {
              return result;
            }
            return {
              ...result,
              highlightedText: result.text,
              semanticMatches: semanticMatches.map((match) => ({
                ...match,
                similarity: 1.0,
              })),
            };
          });
          return { ...prev, [cellKey]: updatedResults };
        });
      } catch (error) {
        console.error(`[Heatmap Highlight] Error for ${chunkId}:`, error);
      } finally {
        processingHighlightsRef.current.delete(chunkId);
      }
    },
    [
      activeCell,
      filteredRowValues,
      rowDimension,
      semanticHighlighting,
      semanticHighlightModelConfig,
    ]
  );

  const updateActiveCellResults = useCallback(
    (updater: (result: SearchResult) => SearchResult) => {
      const cellKey = getActiveCellKey();
      if (!cellKey) {
        return;
      }
      setGridResults((prev) => {
        const cellResults = prev[cellKey];
        if (!cellResults) {
          return prev;
        }
        return {
          ...prev,
          [cellKey]: cellResults.map(updater),
        };
      });
    },
    [getActiveCellKey]
  );

  const handleHeatmapLanguageChange = useCallback(
    async (result: SearchResult, newLang: string) => {
      const originalLanguage = result.language || result.metadata?.language || 'en';
      const activeQuery = activeCell?.query || '';
      if (newLang === originalLanguage) {
        updateActiveCellResults((r) => {
          if (r.chunk_id !== result.chunk_id) {
            return r;
          }
          return {
            ...r,
            translated_snippet: undefined,
            translated_title: undefined,
            translated_headings_display: undefined,
            translated_language: undefined,
            highlightedText: undefined,
          };
        });
        return;
      }

      if (result.translated_language === newLang) {
        return;
      }

      updateActiveCellResults((r) => {
        if (r.chunk_id !== result.chunk_id) {
          return r;
        }
        return { ...r, translated_language: newLang, is_translating: true };
      });

      try {
        const textToTranslate = getChunkTextForTranslation(result);
        const queryToTranslate = activeQuery.trim() ? activeQuery : '';
        const [translatedTitle, translatedText, translatedQuery] = await Promise.all([
          translateWithFallback(result.title, newLang, 'title'),
          translateWithFallback(textToTranslate, newLang, 'text'),
          queryToTranslate
            ? translateWithFallback(queryToTranslate, newLang, 'query')
            : Promise.resolve(queryToTranslate),
        ]);
        const translatedHeadings = await translateHeadings(result.headings, newLang);
        const translatedSemanticMatches = await getTranslatedSemanticMatches(
          translatedText,
          translatedQuery || activeQuery,
          semanticHighlightModelConfig
        );

        updateActiveCellResults((r) => {
          if (r.chunk_id !== result.chunk_id) {
            return r;
          }
          return {
            ...r,
            translated_title: translatedTitle,
            translated_snippet: translatedText,
            translated_headings_display: translatedHeadings,
            translated_language: newLang,
            translatedSemanticMatches: translatedSemanticMatches,
            is_translating: false,
          };
        });
      } catch (error) {
        console.error('Heatmap translation error', error);
        updateActiveCellResults((r) => {
          if (r.chunk_id !== result.chunk_id) {
            return r;
          }
          return { ...r, translated_language: undefined, is_translating: false };
        });
      }
    },
    [activeCell, updateActiveCellResults]
  );

  const filtersPanelProps: FiltersPanelProps = {
    facets,
    selectedFilters: heatmapSelectedFilters,
    collapsedFilters: heatmapCollapsedFilters,
    expandedFilterLists: heatmapExpandedFilterLists,
    filterSearchTerms: heatmapFilterSearchTerms,
    titleSearchResults: heatmapTitleSearchResults,
    facetSearchResults: heatmapFacetSearchResults,
    onRemoveFilter: handleHeatmapRemoveFilter,
    onToggleFilter: toggleHeatmapFilter,
    onFilterSearchTermChange: handleHeatmapFilterSearchTermChange,
    onToggleFilterListExpansion: toggleHeatmapFilterListExpansion,
    onFilterValuesChange: handleHeatmapFilterValuesChange,
    searchDenseWeight,
    onSearchDenseWeightChange,
    keywordBoostShortQueries,
    onKeywordBoostChange,
    semanticHighlighting,
    onSemanticHighlightingChange,
    minScore,
    maxScore,
    onMinScoreChange,
    rerankEnabled,
    onRerankToggle,
    recencyBoostEnabled,
    onRecencyBoostToggle,
    recencyWeight,
    onRecencyWeightChange,
    recencyScaleDays,
    onRecencyScaleDaysChange,
    minChunkSize,
    onMinChunkSizeChange,
    sectionTypes,
    onSectionTypesChange,
  };

  return (
    <div className="main-content">
      <MobileFiltersToggle
        filtersExpanded={filtersExpanded}
        activeFiltersCount={activeFiltersCount}
        onToggle={onToggleFiltersExpanded}
        label="Global Filters"
      />

      <div className={getContentGridClass(filtersExpanded)}>
        <HeatmapFiltersColumn
          filtersExpanded={filtersExpanded}
          onToggleFiltersExpanded={onToggleFiltersExpanded}
          onClearFilters={onClearFilters}
          filtersPanelProps={filtersPanelProps}
        />

        <main className="results-section">
          <div className="heatmap-panel heatmap-panel-with-tab">
            <HeatmapFiltersTabButton
              filtersExpanded={filtersExpanded}
              onToggleFiltersExpanded={onToggleFiltersExpanded}
            />
            <div className="heatmap-controls">
              <div className="heatmap-control">
                <label htmlFor="heatmap-rows">Rows</label>
                <select
                  id="heatmap-rows"
                  className="heatmap-select"
                  value={rowDimension}
                  onChange={(event) => setRowDimension(event.target.value)}
                >
                  {rowOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="heatmap-control">
                <label htmlFor="heatmap-columns">Columns</label>
                <select
                  id="heatmap-columns"
                  className="heatmap-select"
                  value={columnDimension}
                  onChange={(event) => setColumnDimension(event.target.value)}
                >
                  {columnOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="heatmap-control">
                <label htmlFor="heatmap-metric">Metric</label>
                <select
                  id="heatmap-metric"
                  className="heatmap-select"
                  value={heatmapMetric}
                  onChange={(event) => setHeatmapMetric(event.target.value as HeatmapMetric)}
                >
                  <option value="documents">Documents</option>
                  <option value="chunks">Chunks</option>
                </select>
              </div>

              <div className="heatmap-control heatmap-slider">
                <label htmlFor="heatmap-cutoff" style={!scoreBounds.hasScores ? { opacity: 0.4 } : undefined}>
                  Sensitivity: {scoreBounds.hasScores ? similarityCutoff.toFixed(3) : 'n/a'}
                </label>
                <input
                  id="heatmap-cutoff"
                  type="range"
                  min={scoreBounds.min}
                  max={scoreBounds.max}
                  step={0.001}
                  value={similarityCutoff}
                  onChange={(event) => setSimilarityCutoff(Number(event.target.value))}
                  disabled={!scoreBounds.hasScores}
                  title={!scoreBounds.hasScores ? 'Sensitivity requires a search query' : undefined}
                />
              </div>
              <HeatmapActionButtons
                hasCompletedGridSearch={hasCompletedGridSearch}
                handleDownloadExcel={handleDownloadExcel}
                executeGridSearch={executeGridSearch}
                gridLoading={gridLoading}
                hasGridSearchQuery={hasGridSearchQuery}
              />
            </div>

            {gridError && <div className="heatmap-error">{gridError}</div>}

            <HeatmapGridContent
              heatmapReady={heatmapReady}
              filteredColumnValues={filteredColumnValues}
              filteredRowValues={filteredRowValues}
              rowDimension={rowDimension}
              rowOptions={rowOptions}
              columnDimension={columnDimension}
              columnHeaderLabel={columnHeaderLabel}
              gridQuery={gridQuery}
              setGridQuery={setGridQuery}
              rowQueries={rowQueries}
              rowTitleSelections={rowTitleSelections}
              rowTitleInputRefs={rowTitleInputRefs}
              handleRowQueryChange={handleRowQueryChange}
              handleAddRow={handleAddRow}
              handleRemoveRow={handleRemoveRow}
              handleRowTitleSelectionClear={handleRowTitleSelectionClear}
              handleRowTitleSelectionCommit={handleRowTitleSelectionCommit}
              openHeatmapFilterModal={openHeatmapFilterModal}
              isHeatmapFieldFiltered={isHeatmapFieldFiltered}
              filteredGridResults={filteredGridResults}
              maxCellCount={maxCellCount}
              gridLoading={gridLoading}
              openCellModal={openCellModal}
            />
          </div>
        </main>
      </div>

      {heatmapFilterModal && (
        <div className="heatmap-modal-overlay" onClick={closeHeatmapFilterModal}>
          <div className="heatmap-modal heatmap-filter-modal" onClick={(event) => event.stopPropagation()}>
            <div className="heatmap-modal-header">
              <div>
                <h3>Filter {heatmapFilterModal.label}</h3>
                <div className="heatmap-modal-subtitle">
                  Apply filters to heatmap {heatmapFilterModal.field === rowDimension ? 'rows' : 'columns'}.
                </div>
              </div>
              <button className="heatmap-modal-close" onClick={closeHeatmapFilterModal}>
                ×
              </button>
            </div>
            <div className="heatmap-modal-body heatmap-filter-modal-body">
              {heatmapModalFacets && (
                <FilterSections
                  facets={heatmapModalFacets}
                  selectedFilters={heatmapSelectedFilters}
                  collapsedFilters={heatmapCollapsedFilters}
                  expandedFilterLists={heatmapExpandedFilterLists}
                  filterSearchTerms={heatmapFilterSearchTerms}
                  titleSearchResults={orderedHeatmapTitleSearchResults}
                  facetSearchResults={orderedHeatmapFacetSearchResults}
                  onToggleFilter={() => {}}
                  onSearchTermChange={handleHeatmapFilterSearchTermChange}
                  onToggleFilterListExpansion={toggleHeatmapFilterListExpansion}
                  onFilterValuesChange={handleHeatmapFilterValuesChange}
                  renderContentTop={() => (
                    <label className="heatmap-filter-select-all filter-checkbox-item">
                      <div className="filter-checkbox-row">
                        <input
                          ref={selectAllRef}
                          type="checkbox"
                          checked={
                            modalFieldValues.length > 0 &&
                            modalSelectedValues.length === modalFieldValues.length
                          }
                          onChange={toggleHeatmapSelectAll}
                        />
                        <div className="filter-checkbox-text">
                          <span className="filter-checkbox-label">Select all</span>
                        </div>
                      </div>
                    </label>
                  )}
                />
              )}
            </div>
            <div className="heatmap-filter-modal-footer">
              {modalSelectedValues.length === 0 && (
                <span className="heatmap-filter-warning">Please select some fields</span>
              )}
              <div className="heatmap-filter-actions">
                <button
                  type="button"
                  className="search-button heatmap-filter-cancel-button"
                  onClick={cancelHeatmapFilterModal}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="search-button"
                  onClick={closeHeatmapFilterModal}
                  disabled={modalSelectedValues.length === 0}
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {rowDimension === 'title' &&
        Object.entries(rowTitleSearchResults).map(([rowIndexKey, results]) => {
          if (!results || results.length === 0) {
            return null;
          }
          const rowIndex = Number(rowIndexKey);
          if (!Number.isFinite(rowIndex)) {
            return null;
          }
          if (rowTitleSelections[rowIndex]) {
            return null;
          }
          const position = getTitleSuggestionPosition(rowIndex);
          if (!position) {
            return null;
          }
          return createPortal(
            <div
              key={`heatmap-title-suggestions-${rowIndex}`}
              className="heatmap-title-suggestions"
              style={{
                position: 'fixed',
                top: position.top,
                left: position.left,
                width: position.width,
              }}
            >
              {results.map((result) => {
                const subtitleParts = [];
                if (result.organization) subtitleParts.push(result.organization);
                if (result.published_year) subtitleParts.push(result.published_year);
                return (
                  <button
                    key={result.value}
                    type="button"
                    className="heatmap-title-suggestion"
                    onClick={() => {
                      handleRowQueryChange(rowIndex, result.value);
                    setRowTitleSelections((prev) => ({ ...prev, [rowIndex]: result }));
                      setRowTitleSearchResults((prev) => ({ ...prev, [rowIndex]: [] }));
                    }}
                  >
                    <span className="heatmap-title-suggestion-title">{result.value}</span>
                    {subtitleParts.length > 0 && (
                      <span className="heatmap-title-suggestion-subtitle">
                        {subtitleParts.join(' • ')}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>,
            document.body
          );
        })}

      {activeCell && (
        <div className="heatmap-modal-overlay" onClick={closeCellModal}>
          <div className="heatmap-modal" onClick={(event) => event.stopPropagation()}>
            <div className="heatmap-modal-header">
              <div>
                <h3>Results for {activeCell.columnValue}</h3>
                <div className="heatmap-modal-subtitle">{activeCell.query || 'No query'}</div>
              </div>
              <button className="heatmap-modal-close" onClick={closeCellModal}>
                ×
              </button>
            </div>
            <div className="heatmap-modal-content">
              {uniqueActiveCellDocuments.length > 0 && (
                <div className="heatmap-modal-thumbnails">
                <div className="heatmap-modal-thumbnails-label">
                  Documents ({uniqueActiveCellDocuments.length}):
                </div>
                <div className="heatmap-modal-thumbnails-container">
                  {uniqueActiveCellDocuments.map((doc) => {
                    // Try to get sys_parsed_folder from multiple locations with fallback
                    let parsedFolder = doc.sys_parsed_folder;

                    // Check if it's in metadata.sys_data
                    if (!parsedFolder && doc.metadata?.sys_data?.sys_parsed_folder) {
                      parsedFolder = doc.metadata.sys_data.sys_parsed_folder;
                    }

                    // Fallback: construct path from available data
                    if (!parsedFolder && doc.organization && doc.year && doc.doc_id) {
                      const dataSource = doc.data_source || selectedDomain;
                      parsedFolder = `data/${dataSource}/parsed/${doc.organization}/${doc.year}/${doc.doc_id}`;
                    }

                    const thumbnailUrl = parsedFolder
                      ? `${API_BASE_URL}/file/${parsedFolder}/thumbnail.png`
                      : null;
                    const isSelected = filteredDocId === doc.doc_id;
                    return (
                      <div
                        key={doc.doc_id}
                        className={`heatmap-modal-thumbnail ${isSelected ? 'selected' : ''}`}
                        onClick={() => {
                          // Toggle filter for this document
                          setFilteredDocId(isSelected ? null : doc.doc_id);
                        }}
                        title={doc.title || 'No title'}
                      >
                        {thumbnailUrl ? (
                          <img
                            src={thumbnailUrl}
                            alt={doc.title || 'Document thumbnail'}
                            className="heatmap-modal-thumbnail-image"
                            onError={(e) => {
                              // Hide thumbnail on error
                              const target = e.target as HTMLImageElement;
                              target.style.display = 'none';
                            }}
                          />
                        ) : (
                          <div className="heatmap-modal-thumbnail-placeholder">
                            No thumbnail
                          </div>
                        )}
                        <div className="heatmap-modal-thumbnail-title">
                          <div className="heatmap-modal-thumbnail-doc-title">
                            {doc.title || 'Untitled'}
                          </div>
                          {doc.organization && (
                            <div className="heatmap-modal-thumbnail-source">
                              {doc.organization}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="heatmap-modal-body">
              {filteredDocId && (
                <div className="heatmap-modal-filter-indicator">
                  <span className="heatmap-modal-filter-text">
                    Showing results from: <strong>{filteredDocTitle}</strong>
                  </span>
                  <button
                    className="heatmap-modal-filter-clear"
                    onClick={() => setFilteredDocId(null)}
                    title="Clear filter"
                  >
                    × Clear filter
                  </button>
                </div>
              )}
              <SearchResultsList
                results={displayedCellResults}
                minScore={0}
                loading={false}
                query={activeCell.query}
                selectedDoc={selectedDoc}
                onResultClick={onResultClick}
                onOpenMetadata={onOpenMetadata}
                onLanguageChange={handleHeatmapLanguageChange}
                onRequestHighlight={handleHeatmapHighlight}
              />
            </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
