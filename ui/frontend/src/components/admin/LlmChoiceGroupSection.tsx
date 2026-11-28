import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { GroupLlmChoices } from '../../types/auth';

/** One model config.json offers (GET /config/llms). */
export interface OfferedLlm {
  name: string;
  model: string;
  provider: string;
  supports_temperature: boolean;
}

/** config.json's model for each job (GET /config/llm-defaults). */
export interface LlmDefaults {
  summary: string | null;
  brief: string | null;
  judge: string | null;
  citation_check: string | null;
}

type ChoiceKey = keyof GroupLlmChoices;

/** The jobs a group can choose a model for, in the order they are shown. */
export const LLM_JOBS: {
  key: ChoiceKey;
  defaultKey: keyof LlmDefaults;
  label: string;
  help: string;
}[] = [
  {
    key: 'summaryModel',
    defaultKey: 'summary',
    label: 'Search AI summary',
    help: 'Writes the AI summary above search results.',
  },
  {
    key: 'briefModel',
    defaultKey: 'brief',
    label: 'Brief',
    help: "Writes a Brief's outline, its sections and edits.",
  },
  {
    key: 'judgeModel',
    defaultKey: 'judge',
    label: 'Evaluation judge',
    help: 'Scores evaluation runs and the on-demand Brief Fact Check.',
  },
  {
    key: 'citationCheckModel',
    defaultKey: 'citation_check',
    label: 'Automatic citation check',
    help: 'Checks cited passages in Assistant replies and Brief drafts when automatic checking is on.',
  },
];

/** The model choices stored in a group's search_settings. */
export const readLlmChoices = (settings: GroupLlmChoices | null | undefined): GroupLlmChoices => ({
  summaryModel: settings?.summaryModel || undefined,
  briefModel: settings?.briefModel || undefined,
  judgeModel: settings?.judgeModel || undefined,
  citationCheckModel: settings?.citationCheckModel || undefined,
});

/** What a group saves: only the jobs with a chosen model. */
export const llmChoicePayload = (value: GroupLlmChoices): GroupLlmChoices => {
  const payload: GroupLlmChoices = {};
  for (const job of LLM_JOBS) {
    if (value[job.key]) payload[job.key] = value[job.key];
  }
  return payload;
};

const SELECT_STYLE: React.CSSProperties = {
  padding: '0.35rem',
  borderRadius: 4,
  border: '1px solid #d1d5db',
  fontSize: '0.9rem',
  minWidth: '18rem',
  maxWidth: '100%',
};

const optionLabel = (llm: OfferedLlm): string =>
  llm.supports_temperature ? llm.name : `${llm.name} (ignores Response variability)`;

const JobChoice: React.FC<{
  job: (typeof LLM_JOBS)[number];
  value: GroupLlmChoices;
  onChange: (value: GroupLlmChoices) => void;
  llms: OfferedLlm[];
  defaults: LlmDefaults | null;
}> = ({ job, value, onChange, llms, defaults }) => {
  const chosen = value[job.key] ?? '';
  const configDefault = defaults?.[job.defaultKey];
  const offered = !chosen || llms.some((llm) => llm.name === chosen);
  const selectId = `group-llm-${job.key}`;
  return (
    <div className="search-settings-group">
      <label className="search-settings-label" htmlFor={selectId}>
        {job.label}
      </label>
      <select
        id={selectId}
        value={chosen}
        style={SELECT_STYLE}
        onChange={(e) => onChange({ ...value, [job.key]: e.target.value || undefined })}
      >
        <option value="">{job.key === 'citationCheckModel'
          ? `Use evaluation judge (${value.judgeModel || 'selected model combo'})`
          : `Default from config (${configDefault ?? 'none set'})`}</option>
        {llms.map((llm) => (
          <option key={llm.name} value={llm.name}>
            {optionLabel(llm)}
          </option>
        ))}
        {!offered && <option value={chosen}>{chosen} (no longer offered)</option>}
      </select>
      <span className="group-llm-choice-hint">{job.help}</span>
      {!offered && (
        <span role="alert" className="group-llm-choice-alert">
          This site no longer offers {chosen}, so {job.label.toLowerCase()} requests from this group fail
          until you choose another model.
        </span>
      )}
    </div>
  );
};

interface LlmChoiceGroupSectionProps {
  value: GroupLlmChoices;
  onChange: (value: GroupLlmChoices) => void;
}

/** Group Settings > LLMs: which model each AI job uses for this group. */
export const LlmChoiceGroupSection: React.FC<LlmChoiceGroupSectionProps> = ({ value, onChange }) => {
  const [llms, setLlms] = useState<OfferedLlm[]>([]);
  const [defaults, setDefaults] = useState<LlmDefaults | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      axios.get<OfferedLlm[]>(`${API_BASE_URL}/config/llms`),
      axios.get<LlmDefaults>(`${API_BASE_URL}/config/llm-defaults`),
    ])
      .then(([llmResp, defaultsResp]) => {
        if (cancelled) return;
        setLlms(llmResp.data);
        setDefaults(defaultsResp.data);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Could not load the models this site offers.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="group-llm-choices">
      <p className="admin-group-settings-description">
        Choose the model for each AI job for this group&apos;s members. A choice here overrides the
        model set in config.json, including the model combo a user picks; members can&apos;t change it.
        &quot;Default from config&quot; uses config.json&apos;s model. A member of several groups gets the
        choice of the first group by name.
      </p>
      {loadError && (
        <span role="alert" className="group-llm-choice-alert">
          {loadError}
        </span>
      )}
      {LLM_JOBS.map((job) => (
        <JobChoice
          key={job.key}
          job={job}
          value={value}
          onChange={onChange}
          llms={llms}
          defaults={defaults}
        />
      ))}
    </div>
  );
};
