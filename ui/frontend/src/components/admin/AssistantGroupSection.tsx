import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { SummaryModelConfig } from '../../types/api';
import type { AssistantGroupSettings } from '../../types/auth';
import type { OfferedLlm } from './LlmChoiceGroupSection';
import { GroupPromptEditor } from './GroupPromptEditor';
import { CitationCheckSetting } from './CitationCheckSetting';

interface Props {
  value: AssistantGroupSettings;
  onChange: (next: AssistantGroupSettings) => void;
  assistantModelConfig?: SummaryModelConfig | null;
  summaryPrompt: string;
}

const LIMITS = [
  { key: 'searches', label: 'Assistant searches for a focused question', max: 20 },
  { key: 'searchesPerStream', label: 'Assistant searches per stream', max: 6 },
  { key: 'deepSearches', label: 'Deep Research searches for a focused question', max: 20 },
  { key: 'deepSearchesPerStream', label: 'Deep Research searches per stream', max: 6 },
] as const;
const PROMPTS = [
  { key: 'planningInstructions', legacy: 'planningPrompt', label: 'Planning prompt', help: 'Tell the Assistant how to choose follow-up searches.' },
  { key: 'answerInstructions', legacy: 'answerPrompt', label: 'Answer prompt', help: 'Tell the Assistant how to write the final cited answer.' },
] as const;

const readNumber = (input: HTMLInputElement) =>
  input.value === '' ? undefined : input.valueAsNumber;

const numberDefault = (value?: number) => value === undefined ? '' : `${value} (default)`;

const PromptEditor: React.FC<{
  setting: typeof PROMPTS[number];
  value: AssistantGroupSettings;
  defaultPrompt: string;
  inheritedInstructions?: string;
  onChange: Props['onChange'];
}> = ({ setting: { key, legacy, label, help }, value, defaultPrompt, inheritedInstructions, onChange }) => {
  const withInstructions = (instructions?: string) => [instructions?.trim(), defaultPrompt].filter(Boolean).join('\n\n');
  const inherited = withInstructions(inheritedInstructions);
  const displayed = value[key] ?? (value[legacy] === undefined ? undefined : withInstructions(value[legacy]));
  return (
    <GroupPromptEditor id={`group-assistant-${key}`} label={label} help={help}
      value={displayed} defaultPrompt={inherited} disabled={!defaultPrompt}
      onChange={next => onChange({ ...value, [legacy]: undefined, [key]: next })} />
  );
};

export const AssistantGroupSection: React.FC<Props> = ({
  value, onChange, assistantModelConfig, summaryPrompt,
}) => {
  const [models, setModels] = useState<OfferedLlm[]>([]);
  const [defaults, setDefaults] = useState<AssistantGroupSettings>({});
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      axios.get<OfferedLlm[]>(`${API_BASE_URL}/config/llms`),
      axios.get<AssistantGroupSettings>(`${API_BASE_URL}/groups/assistant-defaults`),
    ]).then(([offeredModels, siteDefaults]) => {
        if (cancelled) return;
        setModels(offeredModels.data);
        setDefaults(siteDefaults.data);
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
          <option value="">{assistantModelConfig ? `${assistantModelConfig.model} (default)` : 'Use the selected model combination'}</option>
          {models.map(model => <option key={model.name} value={model.name}>{model.name}{model.supports_temperature ? '' : ' (ignores Response variability)'}</option>)}
          {chosen && !models.some(model => model.name === chosen) && (
            <option value={chosen}>{chosen}</option>
          )}
        </select>
        {loadError && <span role="alert">Could not load the Assistant defaults and models.</span>}
      </div>
      <div className="group-assistant-options">
        <label htmlFor="group-assistant-temperature">Response variability
          <input id="group-assistant-temperature" type="number" min={0} max={1} step={0.05}
            placeholder={numberDefault(assistantModelConfig?.temperature)} value={value.temperature ?? ''}
            onChange={event => onChange({ ...value, temperature: readNumber(event.currentTarget) })} />
        </label>
        <label htmlFor="group-assistant-tokens">Maximum output tokens
          <input id="group-assistant-tokens" type="number" min={1}
            placeholder={numberDefault(assistantModelConfig?.max_tokens)} value={value.maxTokens ?? ''}
            onChange={event => onChange({ ...value, maxTokens: readNumber(event.currentTarget) })} />
        </label>
        <div className="group-assistant-mode">
          <label htmlFor="group-assistant-mode">Starting research mode</label>
          <select id="group-assistant-mode" value={selectedMode} onChange={event => {
            const mode = event.target.value;
            onChange({ ...value, deepResearchByDefault: mode ? mode === 'deep' : undefined });
          }}>
            <option value="">{defaults.deepResearchByDefault ? 'Deep Research' : 'Assistant'} (default)</option>
            <option value="standard">Assistant</option>
            <option value="deep">Deep Research</option>
          </select>
        </div>
      </div>
      <CitationCheckSetting id="group-assistant-citation-check" value={value.citationCheck}
        defaultEnabled={defaults.citationCheck} onChange={next => onChange({ ...value, citationCheck: next })} />
      <fieldset className="group-assistant-options">
        <legend>Search limits</legend>
        {LIMITS.map(({ key, label, max }) => (
          <label key={key} htmlFor={`group-assistant-${key}`}>{label}
            <input id={`group-assistant-${key}`} type="number" min={1} max={max}
              placeholder={numberDefault(defaults[key])} value={value[key] ?? ''}
              onChange={event => onChange({ ...value, [key]: readNumber(event.currentTarget) })} />
          </label>
        ))}
      </fieldset>
      {PROMPTS.map(setting => (
        <PromptEditor key={setting.key} setting={setting} value={value} onChange={onChange}
          defaultPrompt={defaults[setting.key] ?? ''}
          inheritedInstructions={setting.key === 'answerInstructions' ? summaryPrompt : undefined} />
      ))}
    </div>
  );
};
