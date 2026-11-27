import React from 'react';

interface Props {
  id: string;
  label: string;
  help: string;
  defaultPrompt: string;
  value?: string;
  disabled?: boolean;
  onChange: (value: string | undefined) => void;
}

export const GroupPromptEditor: React.FC<Props> = ({
  id, label, help, defaultPrompt, value, disabled = false, onChange,
}) => {
  const customized = value !== undefined;
  return (
    <div className="search-settings-group">
      <label className="search-settings-label" htmlFor={id}>{label}</label>
      <span className="group-llm-choice-hint" id={`${id}-help`}>{help}</span>
      <textarea id={id} className="group-prompt-input" aria-describedby={`${id}-help`}
        rows={10} maxLength={12000} value={value ?? defaultPrompt} disabled={disabled}
        onChange={event => onChange(event.target.value === defaultPrompt ? undefined : event.target.value)}
        onBlur={() => { if (customized && !value.trim()) onChange(undefined); }} />
      <div className="doc-summary-prompt-footer">
        <span className="group-llm-choice-hint">{customized ? 'Custom prompt' : 'Default prompt'}</span>
        <button type="button" className="btn-sm" onClick={() => onChange(undefined)}
          disabled={disabled || !customized} aria-label={`Reset ${label.toLowerCase()} to default`}>
          Reset to Default
        </button>
      </div>
    </div>
  );
};
