import React, { useEffect, useState } from 'react';
import '../documents/summary/documentSummary.css';
import type { DocumentSummaryDefaults } from '../../types/auth';
import { fetchSummaryDefaults } from '../documents/summary/documentSummaryApi';
import {
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

const SectionDefaults: React.FC<{
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
  allSectionTypes: string[];
}> = ({ value, onChange, allSectionTypes }) => {
  const chosen = value.docSummarySectionTypes;
  const toggle = (type: string) => {
    const current = chosen ?? allSectionTypes;
    const next = current.includes(type) ? current.filter((t) => t !== type) : [...current, type];
    onChange({ ...value, docSummarySectionTypes: next });
  };
  return (
    <div className="doc-summary-fieldset">
      <label className="doc-summary-option">
        <input
          type="checkbox"
          checked={!chosen}
          disabled={!allSectionTypes.length}
          onChange={() =>
            onChange({ ...value, docSummarySectionTypes: chosen ? undefined : [...allSectionTypes] })
          }
        />
        <span>Use the data source's sections</span>
      </label>
      {chosen && (
        <div className="doc-summary-sections">
          {allSectionTypes.map((type) => (
            <label key={type} className="doc-summary-option">
              <input type="checkbox" checked={chosen.includes(type)} onChange={() => toggle(type)} />
              <span>{sectionLabel(type)}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
};

const PromptDefault: React.FC<{
  value: DocSummaryGroupValue;
  onChange: (value: DocSummaryGroupValue) => void;
  defaultPrompt: string;
}> = ({ value, onChange, defaultPrompt }) => {
  const custom = value.docSummaryPrompt;
  return (
    <div className="doc-summary-fieldset">
      {custom === undefined ? (
        <>
          <p className="doc-summary-note">Using the default summary prompt.</p>
          <button
            type="button"
            className="btn-sm"
            disabled={!defaultPrompt}
            onClick={() => onChange({ ...value, docSummaryPrompt: defaultPrompt })}
          >
            Customise prompt
          </button>
        </>
      ) : (
        <>
          <textarea
            className="doc-summary-prompt"
            aria-label="Team summary prompt"
            rows={10}
            value={custom}
            onChange={(e) => onChange({ ...value, docSummaryPrompt: e.target.value })}
          />
          <button type="button" className="btn-sm" onClick={() => onChange({ ...value, docSummaryPrompt: undefined })}>
            Use the default prompt
          </button>
        </>
      )}
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

  return (
    <div className="doc-summary-settings">
      <p className="doc-summary-note">
        Used when an administrator regenerates document summaries on the Documents screen. Anything left unset
        uses the data source's settings in config.json. The pipeline always uses config.json.
      </p>
      {error && <p className="doc-summary-error" role="alert">{error}</p>}
      <label className="rerank-checkbox-label" htmlFor="group-doc-summary-mode">
        <span>Mode</span>
      </label>
      <select
        id="group-doc-summary-mode"
        value={value.docSummaryMode ?? DEFAULT_MODE}
        onChange={(e) =>
          onChange({ ...value, docSummaryMode: e.target.value || undefined })
        }
      >
        <option value={DEFAULT_MODE}>Data source default</option>
        {SUMMARY_MODE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="rerank-checkbox-label">Sections</span>
      <SectionDefaults value={value} onChange={onChange} allSectionTypes={defaults?.all_section_types ?? []} />
      <span className="rerank-checkbox-label">Prompt</span>
      <PromptDefault value={value} onChange={onChange} defaultPrompt={defaults?.prompt ?? ''} />
    </div>
  );
};
