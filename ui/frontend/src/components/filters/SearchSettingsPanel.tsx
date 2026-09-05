import React from 'react';

interface SearchSettingsPanelProps {
  collapsedFilters: Set<string>;
  onToggleFilter: (key: string) => void;
  searchDenseWeight: number;
  onSearchDenseWeightChange: (value: number) => void;
  keywordBoostShortQueries: boolean;
  onKeywordBoostChange: (value: boolean) => void;
  semanticHighlighting: boolean;
  onSemanticHighlightingChange: (value: boolean) => void;
  minScore: number;
  maxScore: number;
  onMinScoreChange: (value: number) => void;
  autoMinScore: boolean;
  onAutoMinScoreToggle: (value: boolean) => void;
  rerankEnabled: boolean;
  onRerankToggle: (value: boolean) => void;
  recencyBoostEnabled: boolean;
  onRecencyBoostToggle: (value: boolean) => void;
  recencyWeight: number;
  onRecencyWeightChange: (value: number) => void;
  recencyScaleDays: number;
  onRecencyScaleDaysChange: (value: number) => void;
  minChunkSize: number;
  onMinChunkSizeChange: (value: number) => void;
  sectionTypes: string[];
  onSectionTypesChange: (next: string[]) => void;
  deduplicateEnabled: boolean;
  onDeduplicateToggle: (value: boolean) => void;
  wideSearch: boolean;
  onWideSearchToggle: (value: boolean) => void;
  wideGroupSize: number;
  onWideGroupSizeChange: (value: number) => void;
  wideLimit: number;
  onWideLimitChange: (value: number) => void;
  summaryLimitResults: boolean;
  onSummaryLimitResultsChange: (value: boolean) => void;
  summaryMaxResults: number;
  onSummaryMaxResultsChange: (value: number) => void;
  fieldBoostEnabled: boolean;
  onFieldBoostToggle: (value: boolean) => void;
  fieldBoostFields: Record<string, number>;
  onFieldBoostFieldsChange: (fields: Record<string, number>) => void;
  availableBoostFields: string[];
}

const SUBSETTINGS_GROUP_CLASS = 'settings-subsettings-group';

const BOOST_FIELD_OPTIONS = [
  { value: 'country', label: 'Country' },
  { value: 'organization', label: 'Organization' },
  { value: 'document_type', label: 'Document Type' },
  { value: 'language', label: 'Language' },
];

const SECTION_TYPE_OPTIONS = [
  { value: 'front_matter', label: 'Front Matter' },
  { value: 'executive_summary', label: 'Executive Summary' },
  { value: 'acronyms', label: 'Acronyms' },
  { value: 'context', label: 'Context' },
  { value: 'methodology', label: 'Methodology' },
  { value: 'findings', label: 'Findings' },
  { value: 'conclusions', label: 'Conclusions' },
  { value: 'recommendations', label: 'Recommendations' },
  { value: 'annexes', label: 'Annexes' },
  { value: 'appendix', label: 'Appendix' },
  { value: 'bibliography', label: 'Bibliography' },
  { value: 'other', label: 'Other' },
];

const ScoreSlider = ({
  label,
  value,
  min,
  max,
  step,
  onChange,
  gradient,
  leftLabel,
  rightLabel,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  gradient: string;
  leftLabel: string;
  rightLabel: string;
}) => (
  <div className="search-settings-group">
    <label className="search-settings-label">{label}</label>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(parseFloat(event.target.value))}
      className="score-slider"
      style={{ background: gradient }}
    />
    <div className="score-range-labels">
      <span>{leftLabel}</span>
      <span>{rightLabel}</span>
    </div>
  </div>
);

const RecencyControls = ({
  recencyBoostEnabled,
  onRecencyBoostToggle,
  recencyWeight,
  onRecencyWeightChange,
  recencyScaleDays,
  onRecencyScaleDaysChange,
}: {
  recencyBoostEnabled: boolean;
  onRecencyBoostToggle: (value: boolean) => void;
  recencyWeight: number;
  onRecencyWeightChange: (value: number) => void;
  recencyScaleDays: number;
  onRecencyScaleDaysChange: (value: number) => void;
}) => (
  <div className={recencyBoostEnabled ? SUBSETTINGS_GROUP_CLASS : undefined}>
    <label className="rerank-checkbox-label">
      <input
        type="checkbox"
        checked={recencyBoostEnabled}
        onChange={(event) => onRecencyBoostToggle(event.target.checked)}
        className="rerank-checkbox"
      />
      <span>Boost Recent Reports</span>
      <span
        className="rerank-tooltip"
        title="Prioritize recently published reports in search results. Current year reports get maximum boost."
      >
        ⓘ
      </span>
    </label>

    {recencyBoostEnabled && (
      <>
        <div className="recency-slider-group">
          <label className="recency-slider-label">Recency Weight</label>
          <input
            type="range"
            min="0.05"
            max="0.5"
            step="0.05"
            value={recencyWeight}
            onChange={(event) => onRecencyWeightChange(parseFloat(event.target.value))}
            className="score-slider recency-weight-slider"
          />
          <div className="score-range-labels">
            <span>Subtle</span>
            <span>Strong</span>
          </div>
        </div>

        <div className="recency-slider-group">
          <label className="recency-slider-label">Decay Scale</label>
          <input
            type="range"
            min="180"
            max="1825"
            step="30"
            value={recencyScaleDays}
            onChange={(event) => onRecencyScaleDaysChange(parseInt(event.target.value, 10))}
            className="score-slider recency-scale-slider"
          />
          <div className="score-range-labels">
            <span>6 months</span>
            <span>5 years</span>
          </div>
        </div>
      </>
    )}
  </div>
);

// Wide search: spread results across documents. When on, the search returns
// `wideLimit` documents with at most `wideGroupSize` results each, documents
// ranked by their best match, instead of a flat top-N of chunks.
export const WideSearchControls = ({
  wideSearch,
  onWideSearchToggle,
  wideGroupSize,
  onWideGroupSizeChange,
  wideLimit,
  onWideLimitChange,
}: {
  wideSearch: boolean;
  onWideSearchToggle: (value: boolean) => void;
  wideGroupSize: number;
  onWideGroupSizeChange: (value: number) => void;
  wideLimit: number;
  onWideLimitChange: (value: number) => void;
}) => (
  <div className={wideSearch ? SUBSETTINGS_GROUP_CLASS : undefined}>
    <label className="rerank-checkbox-label">
      <input
        type="checkbox"
        checked={wideSearch}
        onChange={(event) => onWideSearchToggle(event.target.checked)}
        className="rerank-checkbox"
      />
      <span>Wide Search</span>
      <span
        className="rerank-tooltip"
        title="Spread results across more documents: return a set number of documents with at most a few results each, ranked by each document's best match. Use it when one document is crowding out the rest."
      >
        ⓘ
      </span>
    </label>
    {wideSearch && (
      <div className="wide-search-fields">
        <label className="wide-search-field">
          <span className="wide-search-label">Max results per document</span>
          <input
            type="number"
            min="1"
            max="50"
            step="1"
            value={wideGroupSize}
            aria-label="Max results per document"
            onChange={(event) => {
              const v = parseInt(event.target.value, 10);
              if (!isNaN(v)) onWideGroupSizeChange(Math.min(50, Math.max(1, v)));
            }}
            className="wide-search-number"
          />
        </label>
        <label className="wide-search-field">
          <span className="wide-search-label">Number of documents</span>
          <input
            type="number"
            min="1"
            max="200"
            step="1"
            value={wideLimit}
            aria-label="Number of documents"
            onChange={(event) => {
              const v = parseInt(event.target.value, 10);
              if (!isNaN(v)) onWideLimitChange(Math.min(200, Math.max(1, v)));
            }}
            className="wide-search-number"
          />
        </label>
      </div>
    )}
  </div>
);

// AI Summary: how many of the results it is built from. Off = every result.
export const AiSummaryControls = ({
  summaryLimitResults,
  onSummaryLimitResultsChange,
  summaryMaxResults,
  onSummaryMaxResultsChange,
}: {
  summaryLimitResults: boolean;
  onSummaryLimitResultsChange: (value: boolean) => void;
  summaryMaxResults: number;
  onSummaryMaxResultsChange: (value: number) => void;
}) => (
  <div className={summaryLimitResults ? SUBSETTINGS_GROUP_CLASS : undefined}>
    <label className="rerank-checkbox-label">
      <input
        type="checkbox"
        checked={summaryLimitResults}
        onChange={(event) => onSummaryLimitResultsChange(event.target.checked)}
        className="rerank-checkbox"
      />
      <span>Limit Results Used</span>
      <span
        className="rerank-tooltip"
        title="Build the AI Summary from at most this many results. Turn off to give the summary every result on the page (slower and costlier, but nothing is left out)."
      >
        ⓘ
      </span>
    </label>
    {summaryLimitResults && (
      <div className="wide-search-fields">
        <label className="wide-search-field">
          <span className="wide-search-label">Max results for summary</span>
          <input
            type="number"
            min="1"
            max="200"
            step="1"
            value={summaryMaxResults}
            aria-label="Max results for summary"
            onChange={(event) => {
              const v = parseInt(event.target.value, 10);
              if (!isNaN(v)) onSummaryMaxResultsChange(Math.min(200, Math.max(1, v)));
            }}
            className="wide-search-number"
          />
        </label>
      </div>
    )}
  </div>
);

const SectionTypesSelector = ({
  sectionTypes,
  onSectionTypesChange,
}: {
  sectionTypes: string[];
  onSectionTypesChange: (next: string[]) => void;
}) => (
  <>
    <div className="content-type-label">
      <span>Section Type</span>
      <span
        className="rerank-tooltip"
        title="Filter by document section type. Leave all unchecked to include all sections."
      >
        ⓘ
      </span>
    </div>
    <label className="section-type-checkbox" style={{ marginBottom: '0.5em', fontWeight: '600' }}>
      <input
        type="checkbox"
        checked={sectionTypes.length === SECTION_TYPE_OPTIONS.length}
        ref={(el) => {
          if (el) {
            el.indeterminate =
              sectionTypes.length > 0 && sectionTypes.length < SECTION_TYPE_OPTIONS.length;
          }
        }}
        onChange={(event) => {
          if (event.target.checked) {
            onSectionTypesChange(SECTION_TYPE_OPTIONS.map((item) => item.value));
          } else {
            onSectionTypesChange([]);
          }
        }}
      />
      <span>Select All</span>
    </label>
    <div className="section-type-options">
      {SECTION_TYPE_OPTIONS.map(({ value, label }) => (
        <label key={value} className="section-type-checkbox">
          <input
            type="checkbox"
            checked={sectionTypes.includes(value)}
            onChange={(event) => {
              if (event.target.checked) {
                onSectionTypesChange([...sectionTypes, value]);
              } else {
                onSectionTypesChange(sectionTypes.filter((item) => item !== value));
              }
            }}
          />
          <span>{label}</span>
        </label>
      ))}
    </div>
  </>
);

export const SearchSettingsPanel = ({
  collapsedFilters,
  onToggleFilter,
  searchDenseWeight,
  onSearchDenseWeightChange,
  keywordBoostShortQueries,
  onKeywordBoostChange,
  semanticHighlighting,
  onSemanticHighlightingChange,
  minScore,
  maxScore,
  onMinScoreChange,
  autoMinScore,
  onAutoMinScoreToggle,
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
  deduplicateEnabled,
  onDeduplicateToggle,
  wideSearch,
  onWideSearchToggle,
  wideGroupSize,
  onWideGroupSizeChange,
  wideLimit,
  onWideLimitChange,
  summaryLimitResults,
  onSummaryLimitResultsChange,
  summaryMaxResults,
  onSummaryMaxResultsChange,
  fieldBoostEnabled,
  onFieldBoostToggle,
  fieldBoostFields,
  onFieldBoostFieldsChange,
  availableBoostFields,
}: SearchSettingsPanelProps) => (
  <>
    <div className="filter-section">
      <div className="filter-section-header" onClick={() => onToggleFilter('search_settings')}>
        <span className="filter-section-toggle">
          {collapsedFilters.has('search_settings') ? '▼' : '▶'}
        </span>
        <span className="filter-section-title">Search Settings</span>
      </div>
      {collapsedFilters.has('search_settings') && (
        <div className="filter-section-content">
          <ScoreSlider
            label="Search Mode"
            value={searchDenseWeight}
            min={0}
            max={1}
            step={0.1}
            onChange={onSearchDenseWeightChange}
            gradient={`linear-gradient(to right,
              #93c5fd ${searchDenseWeight * 100}%,
              #0066cc ${searchDenseWeight * 100}%)`}
            leftLabel="Keyword"
            rightLabel="Semantic"
          />
          <label className="rerank-checkbox-label">
            <input
              type="checkbox"
              checked={keywordBoostShortQueries}
              onChange={(event) => onKeywordBoostChange(event.target.checked)}
              className="rerank-checkbox"
            />
            <span>Keyword Boost Short Queries</span>
            <span
              className="rerank-tooltip"
              title="When enabled, queries with 2 words or less automatically use lower semantic weight for better keyword matching."
            >
              ⓘ
            </span>
          </label>
          <label className="rerank-checkbox-label">
            <input
              type="checkbox"
              checked={semanticHighlighting}
              onChange={(event) => onSemanticHighlightingChange(event.target.checked)}
              className="rerank-checkbox"
            />
            <span>Semantic Highlighting</span>
            <span
              className="rerank-tooltip"
              title="Use advanced AI to highlight semantically relevant phrases in search results."
            >
              ⓘ
            </span>
          </label>
          <div className="search-settings-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <label className="search-settings-label">Min Score{!autoMinScore && `: ${minScore.toFixed(3)}`}</label>
              <label style={{ fontSize: '0.875rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <input
                  type="checkbox"
                  checked={autoMinScore}
                  onChange={(e) => onAutoMinScoreToggle(e.target.checked)}
                  style={{ cursor: 'pointer' }}
                />
                <span>Auto</span>
              </label>
            </div>
            {!autoMinScore && (
              <>
                <input
                  type="range"
                  min={0}
                  max={maxScore}
                  step={0.001}
                  value={minScore}
                  onChange={(event) => onMinScoreChange(parseFloat(event.target.value))}
                  className="score-slider"
                  style={{
                    background: `linear-gradient(to right,
                      #d1d5db 0%,
                      #d1d5db ${(minScore / maxScore) * 100}%,
                      #0066cc ${(minScore / maxScore) * 100}%,
                      #0066cc 100%)`
                  }}
                />
                <div className="score-range-labels">
                  <span>0.000</span>
                  <span>{maxScore.toFixed(3)}</span>
                </div>
              </>
            )}
            {autoMinScore && (
              <div style={{ fontSize: '0.75rem', color: '#6b7280', fontStyle: 'italic' }}>
                &nbsp;
              </div>
            )}
          </div>
          <label className="rerank-checkbox-label">
            <input
              type="checkbox"
              checked={rerankEnabled}
              onChange={(event) => onRerankToggle(event.target.checked)}
              className="rerank-checkbox"
            />
            <span>Enable Reranker</span>
            <span
              className="rerank-tooltip"
              title="Use a cross-encoder model to rerank results for better relevance. May be slower."
            >
              ⓘ
            </span>
          </label>
          <RecencyControls
            recencyBoostEnabled={recencyBoostEnabled}
            onRecencyBoostToggle={onRecencyBoostToggle}
            recencyWeight={recencyWeight}
            onRecencyWeightChange={onRecencyWeightChange}
            recencyScaleDays={recencyScaleDays}
            onRecencyScaleDaysChange={onRecencyScaleDaysChange}
          />
          <label className="rerank-checkbox-label">
            <input
              type="checkbox"
              checked={deduplicateEnabled}
              onChange={(event) => onDeduplicateToggle(event.target.checked)}
              className="rerank-checkbox"
            />
            <span>Deduplicate</span>
            <span
              className="rerank-tooltip"
              title="Deduplicate content found in multiple reports"
            >
              ⓘ
            </span>
          </label>
          <WideSearchControls
            wideSearch={wideSearch}
            onWideSearchToggle={onWideSearchToggle}
            wideGroupSize={wideGroupSize}
            onWideGroupSizeChange={onWideGroupSizeChange}
            wideLimit={wideLimit}
            onWideLimitChange={onWideLimitChange}
          />
          <div className={fieldBoostEnabled ? SUBSETTINGS_GROUP_CLASS : undefined}>
          <label className="rerank-checkbox-label">
            <input
              type="checkbox"
              checked={fieldBoostEnabled}
              onChange={(event) => onFieldBoostToggle(event.target.checked)}
              className="rerank-checkbox"
            />
            <span>Field Level Boosting</span>
            <span
              className="rerank-tooltip"
              title="Boost fields such as organization and country if configured for this data source"
            >
              ⓘ
            </span>
          </label>
          {fieldBoostEnabled && (
            <div className="field-boost-fields">
              {BOOST_FIELD_OPTIONS
                .filter(({ value }) => availableBoostFields.includes(value))
                .map(({ value, label }) => {
                  const isChecked = value in fieldBoostFields;
                  const weight = fieldBoostFields[value] ?? 0.5;
                  return (
                    <div key={value} className="field-boost-row">
                      <label className="section-type-checkbox">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(event) => {
                            if (event.target.checked) {
                              onFieldBoostFieldsChange({ ...fieldBoostFields, [value]: 0.5 });
                            } else {
                              const next = { ...fieldBoostFields };
                              delete next[value];
                              onFieldBoostFieldsChange(next);
                            }
                          }}
                        />
                        <span>{label}</span>
                      </label>
                      {isChecked && (
                        <input
                          type="number"
                          min="0.1"
                          max="2.0"
                          step="0.1"
                          value={weight}
                          onChange={(event) => {
                            const v = parseFloat(event.target.value);
                            if (!isNaN(v)) {
                              onFieldBoostFieldsChange({
                                ...fieldBoostFields,
                                [value]: v,
                              });
                            }
                          }}
                          className="field-boost-input"
                        />
                      )}
                    </div>
                  );
                })}
            </div>
          )}
          </div>
        </div>
      )}
    </div>

    <div className="filter-section">
      <div className="filter-section-header" onClick={() => onToggleFilter('content_settings')}>
        <span className="filter-section-toggle">
          {collapsedFilters.has('content_settings') ? '▼' : '▶'}
        </span>
        <span className="filter-section-title">Content Settings</span>
      </div>
      {collapsedFilters.has('content_settings') && (
        <div className="filter-section-content">
          <div
            className="search-settings-group"
            style={{ marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid #e5e7eb' }}
          >
            <label
              className="search-settings-label"
              title="Filter out chunks with fewer characters than this value. Default is 100 chars."
            >
              Min Chunk Size: {minChunkSize} chars
              <span
                className="rerank-tooltip"
                title="Filter out chunks with fewer characters than this value. Helps remove noise like headers, footers, and fragmented sentences."
              >
                ⓘ
              </span>
            </label>
            <input
              type="range"
              min="0"
              max="1000"
              step="50"
              value={minChunkSize}
              onChange={(event) => onMinChunkSizeChange(parseInt(event.target.value, 10))}
              className="score-slider"
              style={{
                background: `linear-gradient(to right,
                  #93c5fd ${(minChunkSize / 1000) * 100}%,
                  #e5e7eb ${(minChunkSize / 1000) * 100}%)`,
              }}
            />
            <div className="score-range-labels">
              <span>0 (All)</span>
              <span>1000</span>
            </div>
          </div>
          <SectionTypesSelector
            sectionTypes={sectionTypes}
            onSectionTypesChange={onSectionTypesChange}
          />
        </div>
      )}
    </div>

    <div className="filter-section">
      <div className="filter-section-header" onClick={() => onToggleFilter('ai_summary_settings')}>
        <span className="filter-section-toggle">
          {collapsedFilters.has('ai_summary_settings') ? '▼' : '▶'}
        </span>
        <span className="filter-section-title">AI Summary</span>
      </div>
      {collapsedFilters.has('ai_summary_settings') && (
        <div className="filter-section-content">
          <AiSummaryControls
            summaryLimitResults={summaryLimitResults}
            onSummaryLimitResultsChange={onSummaryLimitResultsChange}
            summaryMaxResults={summaryMaxResults}
            onSummaryMaxResultsChange={onSummaryMaxResultsChange}
          />
        </div>
      )}
    </div>
  </>
);
