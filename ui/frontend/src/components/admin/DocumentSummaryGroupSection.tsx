import React, { useEffect, useState } from 'react';
import '../documents/summary/documentSummary.css';
import type { DocumentSummaryDefaults } from '../../types/auth';
import { fetchSummaryDefaults } from '../documents/summary/documentSummaryApi';
import {
  DataSourceSummaryDefaults,
  SUMMARY_MODE_OPTIONS,
  SummaryConfigDefaults,
  sectionLabel,
} from '../documents/summary/summarySettings';

const DEFAULT_MODE = '';

/** A group's document summary defaults; unset keys use the data source config. */
export type DocSummaryGroupValue = DocumentSummaryDefaults;

/** The document summary defaults stored in a group's search_settings. */
export const readDocSummaryDefaults = (
  settings: DocumentSummaryDefaults | null | undefined,
): DocSummaryGroupValue => ({
  docSummaryMode: settings?.docSummaryMode || undefined,
  docSummarySectionTypes: settings?.docSummarySectionTypes ?? undefined,
  docSummaryPrompt: settings?.docSummaryPrompt || undefined,
});

/** What a group saves: only the keys that are set (a blank prompt is unset). */
export const docSummaryPayload = (value: DocSummaryGroupValue): DocSummaryGroupValue => {
  const payload: DocSummaryGroupValue = {};
  if (value.docSummaryMode) payload.docSummaryMode = value.docSummaryMode;
  if (value.docSummarySectionTypes?.length) payload.docSummarySectionTypes = value.docSummarySectionTypes;
  if (value.docSummaryPrompt?.trim()) payload.docSummaryPrompt = value.docSummaryPrompt;
  return payload;
};

interface DocumentSummaryGroupSectionProps {
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
}

const optionLabel = (mode: string): string =>
  SUMMARY_MODE_OPTIONS.find((o) => o.value === mode)?.label ?? mode;

/** "WFP Evaluation Reports: Map reduce" for each data source. */
const sourceModes = (sources: DataSourceSummaryDefaults[]): string =>
  sources.map((ds) => `${ds.name}: ${optionLabel(ds.mode)}`).join(' · ');

const ModeChoice: React.FC<{
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
  sources: DataSourceSummaryDefaults[];
}> = ({ value, onChange, sources }) => {
  const options = [
    { value: DEFAULT_MODE, label: "Data source's mode", hint: sources.length ? sourceModes(sources) : '' },
    ...SUMMARY_MODE_OPTIONS,
  ];
  return (
    <div className="search-settings-group" role="radiogroup" aria-label="Summary mode">
      <span className="search-settings-label">Summary mode</span>
      {options.map((option) => (
        <label key={option.value || 'default'} className="rerank-checkbox-label doc-summary-choice-row">
          <input
            type="radio"
            name="group-doc-summary-mode"
            className="rerank-checkbox"
            checked={(value.docSummaryMode ?? DEFAULT_MODE) === option.value}
            onChange={() => onChange({ ...value, docSummaryMode: option.value || undefined })}
          />
          <span>{option.label}</span>
          {option.hint && <span className="doc-summary-choice-hint">{option.hint}</span>}
        </label>
      ))}
    </div>
  );
};

/** The sections each data source summarises, as chips in the standard order. */
const SourceSections: React.FC<{ sources: DataSourceSummaryDefaults[]; allSectionTypes: string[] }> = ({
  sources,
  allSectionTypes,
}) => (
  <div className="doc-summary-source-sections">
    {sources.map((ds) => (
      <div key={ds.key} className="doc-summary-source">
        <span className="doc-summary-source-name">{ds.name}</span>
        {allSectionTypes
          .filter((type) => ds.section_types.includes(type))
          .map((type) => (
            <span key={type} className="doc-summary-chip">
              {sectionLabel(type)}
            </span>
          ))}
      </div>
    ))}
  </div>
);

const SectionDefaults: React.FC<{
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
  allSectionTypes: string[];
  sources: DataSourceSummaryDefaults[];
}> = ({ value, onChange, allSectionTypes, sources }) => {
  const chosen = value.docSummarySectionTypes;
  const toggle = (type: string) => {
    const current = chosen ?? allSectionTypes;
    const next = current.includes(type) ? current.filter((t) => t !== type) : [...current, type];
    onChange({ ...value, docSummarySectionTypes: next });
  };
  return (
    <div className="search-settings-group">
      <span className="search-settings-label">Sections</span>
      <div className="settings-subsettings-group">
        <label className="rerank-checkbox-label">
          <input
            type="checkbox"
            className="rerank-checkbox"
            checked={!chosen}
            disabled={!allSectionTypes.length}
            onChange={() => onChange({ ...value, docSummarySectionTypes: chosen ? undefined : [...allSectionTypes] })}
          />
          <span>Use the data source's sections</span>
        </label>
        {chosen ? (
          <div className="doc-summary-sections doc-summary-section-picks">
            {allSectionTypes.map((type) => (
              <label key={type} className="doc-summary-option">
                <input type="checkbox" checked={chosen.includes(type)} onChange={() => toggle(type)} />
                <span>{sectionLabel(type)}</span>
              </label>
            ))}
          </div>
        ) : (
          <SourceSections sources={sources} allSectionTypes={allSectionTypes} />
        )}
      </div>
    </div>
  );
};

const PromptDefault: React.FC<{
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
  defaultPrompt: string;
}> = ({ value, onChange, defaultPrompt }) => {
  const custom = value.docSummaryPrompt;
  const shown = custom ?? defaultPrompt;
  return (
    <div className="search-settings-group">
      <label className="search-settings-label" htmlFor="group-doc-summary-prompt">
        Summary prompt
      </label>
      <textarea
        id="group-doc-summary-prompt"
        className="doc-summary-prompt"
        aria-label="Team summary prompt"
        rows={12}
        value={shown}
        disabled={!defaultPrompt}
        onChange={(e) =>
          onChange({ ...value, docSummaryPrompt: e.target.value === defaultPrompt ? undefined : e.target.value })
        }
      />
      <div className="doc-summary-prompt-footer">
        <span className="doc-summary-note">
          {custom === undefined ? 'The default summary prompt.' : 'A custom prompt for this group.'}
        </span>
        <button
          type="button"
          className="btn-sm"
          disabled={custom === undefined}
          onClick={() => onChange({ ...value, docSummaryPrompt: undefined })}
        >
          Reset to default
        </button>
      </div>
    </div>
  );
};

/**
 * Group defaults for document summaries generated on the Documents screen:
 * mode, sections and prompt. Each can be left to the data source's config.
 * They never affect summaries written by the pipeline.
 */
export const DocumentSummaryGroupSection: React.FC<DocumentSummaryGroupSectionProps> = ({ value, onChange }) => {
  const [defaults, setDefaults] = useState<SummaryConfigDefaults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSummaryDefaults()
      .then(setDefaults)
      .catch(() => setError('The summary defaults could not be loaded.'));
  }, []);

  const sources = defaults?.data_sources ?? [];
  return (
    <div className="doc-summary-group">
      <p className="doc-summary-note">
        Used when an administrator regenerates document summaries on the Documents screen; each can be changed
        there. Anything left to the data source uses its settings in config.json, and the pipeline always does.
      </p>
      {error && <p className="doc-summary-error" role="alert">{error}</p>}
      <ModeChoice value={value} onChange={onChange} sources={sources} />
      <SectionDefaults
        value={value}
        onChange={onChange}
        allSectionTypes={defaults?.all_section_types ?? []}
        sources={sources}
      />
      <PromptDefault value={value} onChange={onChange} defaultPrompt={defaults?.prompt ?? ''} />
    </div>
  );
};
