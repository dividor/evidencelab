import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { AssistantGroupSettings } from '../../types/auth';
import type { OfferedLlm } from './LlmChoiceGroupSection';

interface Props {
  value: AssistantGroupSettings;
  onChange: (next: AssistantGroupSettings) => void;
}

const LIMITS = [
  { key: 'searches', label: 'Assistant searches for a focused question', max: 20 },
  { key: 'searchesPerStream', label: 'Assistant searches per stream', max: 6 },
  { key: 'deepSearches', label: 'Deep Research searches for a focused question', max: 20 },
  { key: 'deepSearchesPerStream', label: 'Deep Research searches per stream', max: 6 },
] as const;
const PROMPTS = [
  { key: 'planningPrompt', label: 'Planning prompt', help: 'Add instructions for splitting questions and choosing follow-up searches.' },
  { key: 'answerPrompt', label: 'Answer prompt', help: 'Add instructions for the final cited answer. Leave blank to keep the group’s AI Summary instructions.' },
] as const;

const readNumber = (input: HTMLInputElement) =>
  input.value === '' ? undefined : input.valueAsNumber;

export const AssistantGroupSection: React.FC<Props> = ({ value, onChange }) => {
  const [models, setModels] = useState<OfferedLlm[]>([]);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get<OfferedLlm[]>(`${API_BASE_URL}/config/llms`)
      .then(response => {
        if (!cancelled) setModels(response.data);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => { cancelled = true; };
  }, []);

  const chosen = value.model || '';
  const selectedMode = value.deepResearchByDefault === undefined
    ? ''
    : value.deepResearchByDefault ? 'deep' : 'standard';

  return (
    <div className="group-assistant-settings">
      <div className="search-settings-group">
        <label className="search-settings-label" htmlFor="group-assistant-model">Model</label>
        <select id="group-assistant-model" value={chosen}
          onChange={event => onChange({ ...value, model: event.target.value || undefined })}>
          <option value="">Use the selected model combination</option>
          {models.map(model => <option key={model.name} value={model.name}>{model.name}{model.supports_temperature ? '' : ' (ignores Response variability)'}</option>)}
          {chosen && !models.some(model => model.name === chosen) && (
            <option value={chosen}>{chosen}</option>
          )}
        </select>
        {loadError && <span role="alert">Could not load the available Assistant models.</span>}
      </div>
      <div className="group-assistant-options">
        <label htmlFor="group-assistant-temperature">Response variability
          <input id="group-assistant-temperature" type="number" min={0} max={1} step={0.05}
            placeholder="Model default" value={value.temperature ?? ''}
            onChange={event => onChange({ ...value, temperature: readNumber(event.currentTarget) })} />
        </label>
        <label htmlFor="group-assistant-tokens">Maximum output tokens
          <input id="group-assistant-tokens" type="number" min={1}
            placeholder="Model default" value={value.maxTokens ?? ''}
            onChange={event => onChange({ ...value, maxTokens: readNumber(event.currentTarget) })} />
        </label>
        <div className="group-assistant-mode">
          <label htmlFor="group-assistant-mode">Starting research mode</label>
          <select id="group-assistant-mode" value={selectedMode} onChange={event => {
            const mode = event.target.value;
            onChange({ ...value, deepResearchByDefault: mode ? mode === 'deep' : undefined });
          }}>
            <option value="">Use site default</option>
            <option value="standard">Assistant</option>
            <option value="deep">Deep Research</option>
          </select>
        </div>
      </div>
      <fieldset className="group-assistant-options">
        <legend>Search limits</legend>
        {LIMITS.map(({ key, label, max }) => (
          <label key={key} htmlFor={`group-assistant-${key}`}>{label}
            <input id={`group-assistant-${key}`} type="number" min={1} max={max}
              placeholder="Site default" value={value[key] ?? ''}
              onChange={event => onChange({ ...value, [key]: readNumber(event.currentTarget) })} />
          </label>
        ))}
      </fieldset>
      {PROMPTS.map(({ key, label, help }) => (
        <div className="search-settings-group" key={key}>
          <label className="search-settings-label" htmlFor={`group-assistant-${key}`}>{label}</label>
          <span className="group-llm-choice-hint" id={`group-assistant-${key}-help`}>{help}</span>
          <textarea id={`group-assistant-${key}`} aria-describedby={`group-assistant-${key}-help`}
            rows={5} maxLength={12000} value={value[key] || ''}
            onChange={event => onChange({ ...value, [key]: event.target.value || undefined })} />
        </div>
      ))}
    </div>
  );
};
