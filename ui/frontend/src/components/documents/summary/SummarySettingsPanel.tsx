import React from 'react';
import {
  DocumentSections,
  SUMMARY_MODE_OPTIONS,
  SummaryMode,
  SummarySettings,
  formatChars,
  sectionLabel,
  selectedChars,
  singlePromptFit,
} from './summarySettings';

interface SummarySettingsPanelProps {
  settings: SummarySettings;
  onChange: (settings: SummarySettings) => void;
  /** Every section type, in order (used when the document's sizes are unknown). */
  allSectionTypes: string[];
  /** The default prompt, for "Reset to default". */
  defaultPrompt: string;
  /** One document's text per section; omitted for several documents. */
  sections?: DocumentSections | null;
  disabled?: boolean;
}

const FitNote: React.FC<{ sections: DocumentSections; chosen: string[] }> = ({ sections, chosen }) => {
  const fit = singlePromptFit(sections, chosen);
  const chars = formatChars(selectedChars(sections, chosen));
  if (fit === 'unavailable') {
    return <p className="doc-summary-note doc-summary-note-warn">Single prompt is not set up for this data source.</p>;
  }
  const limit = formatChars(sections.single_prompt_limit_chars ?? 0);
  return fit === 'fits' ? (
    <p className="doc-summary-note">About {chars} characters of text; a single prompt takes up to {limit}.</p>
  ) : (
    <p className="doc-summary-note doc-summary-note-warn">
      About {chars} characters of text, more than the {limit} a single prompt takes. Choose fewer sections or use
      map reduce.
    </p>
  );
};

const ModeChoice: React.FC<{
  mode: SummaryMode;
  onChange: (mode: SummaryMode) => void;
  disabled?: boolean;
}> = ({ mode, onChange, disabled }) => (
  <fieldset className="doc-summary-fieldset">
    <legend>Mode</legend>
    {SUMMARY_MODE_OPTIONS.map((option) => (
      <label key={option.value} className="doc-summary-option">
        <input
          type="radio"
          name="doc-summary-mode"
          value={option.value}
          checked={mode === option.value}
          disabled={disabled}
          onChange={() => onChange(option.value)}
        />
        <span>
          <strong>{option.label}</strong> — {option.hint}
        </span>
      </label>
    ))}
  </fieldset>
);

const SectionChoice: React.FC<{
  chosen: string[];
  onChange: (sectionTypes: string[]) => void;
  allSectionTypes: string[];
  sections?: DocumentSections | null;
  disabled?: boolean;
}> = ({ chosen, onChange, allSectionTypes, sections, disabled }) => {
  if (sections && !sections.has_section_types) {
    return (
      <fieldset className="doc-summary-fieldset">
        <legend>Sections</legend>
        <p className="doc-summary-note">
          This document has no section types yet, so all its text is used.
        </p>
      </fieldset>
    );
  }
  const sizes = new Map((sections?.sections ?? []).map((s) => [s.section_type, s.chars]));
  const types = sections ? sections.sections.map((s) => s.section_type) : allSectionTypes;
  const toggle = (type: string) =>
    onChange(chosen.includes(type) ? chosen.filter((t) => t !== type) : [...chosen, type]);
  return (
    <fieldset className="doc-summary-fieldset">
      <legend>Sections</legend>
      <div className="doc-summary-sections">
        {types.map((type) => (
          <label key={type} className="doc-summary-option">
            <input
              type="checkbox"
              checked={chosen.includes(type)}
              disabled={disabled}
              onChange={() => toggle(type)}
            />
            <span>
              {sectionLabel(type)}
              {sizes.has(type) && <span className="doc-summary-size"> · {formatChars(sizes.get(type)!)}</span>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
};

/** Mode, sections and prompt for generating document summaries. */
export const SummarySettingsPanel: React.FC<SummarySettingsPanelProps> = ({
  settings,
  onChange,
  allSectionTypes,
  defaultPrompt,
  sections,
  disabled,
}) => (
  <div className="doc-summary-settings">
    <ModeChoice mode={settings.mode} onChange={(mode) => onChange({ ...settings, mode })} disabled={disabled} />
    <SectionChoice
      chosen={settings.sectionTypes}
      onChange={(sectionTypes) => onChange({ ...settings, sectionTypes })}
      allSectionTypes={allSectionTypes}
      sections={sections}
      disabled={disabled}
    />
    {sections && settings.mode === 'single_prompt' && (
      <FitNote sections={sections} chosen={settings.sectionTypes} />
    )}
    <fieldset className="doc-summary-fieldset">
      <legend>Prompt</legend>
      <textarea
        className="doc-summary-prompt"
        aria-label="Summary prompt"
        value={settings.prompt}
        disabled={disabled}
        rows={8}
        onChange={(e) => onChange({ ...settings, prompt: e.target.value })}
      />
      <button
        type="button"
        className="btn-sm"
        disabled={disabled || settings.prompt === defaultPrompt}
        onClick={() => onChange({ ...settings, prompt: defaultPrompt })}
      >
        Reset to default
      </button>
    </fieldset>
  </div>
);
