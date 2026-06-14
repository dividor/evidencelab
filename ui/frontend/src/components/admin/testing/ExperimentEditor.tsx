import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type {
  AssertionMatrix as MatrixValue,
  CaseRowState,
  TestCase,
  TestDataset,
  TestExperiment,
} from '../../../types/testing';
import AssertionMatrix from './AssertionMatrix';

interface ExperimentEditorProps {
  // When editing an existing draft, the experiment is provided.
  experiment?: TestExperiment | null;
  // Pre-selected dataset when creating from a dataset context (optional).
  initialDatasetId?: string | null;
  onBack: () => void;
  // Called with the (possibly new) experiment id once it has been saved.
  onSaved: (experimentId: string) => void;
}

/* ------------------------------------------------------------------ */
/*  Config form                                                       */
/* ------------------------------------------------------------------ */

interface ConfigDraft {
  summary_model: string;
  limit: string;
  rerank: boolean;
  temperature: string;
  max_tokens: string;
}

const configToDraft = (config?: Record<string, unknown> | null): ConfigDraft => {
  const c = config || {};
  const num = (v: unknown): string => (v === null || v === undefined ? '' : String(v));
  return {
    summary_model: typeof c.summary_model === 'string' ? c.summary_model : '',
    limit: num(c.limit),
    rerank: Boolean(c.rerank),
    temperature: num(c.temperature),
    max_tokens: num(c.max_tokens),
  };
};

const parseNumeric = (raw: string): number | undefined => {
  const trimmed = raw.trim();
  if (trimmed === '') return undefined;
  const n = Number(trimmed);
  return Number.isNaN(n) ? undefined : n;
};

const draftToConfig = (draft: ConfigDraft): Record<string, unknown> => {
  const config: Record<string, unknown> = {
    rerank: draft.rerank,
  };
  if (draft.summary_model.trim()) config.summary_model = draft.summary_model.trim();
  const parsedLimit = parseNumeric(draft.limit);
  if (parsedLimit !== undefined) config.limit = parsedLimit;
  const parsedTemp = parseNumeric(draft.temperature);
  if (parsedTemp !== undefined) config.temperature = parsedTemp;
  const parsedTokens = parseNumeric(draft.max_tokens);
  if (parsedTokens !== undefined) config.max_tokens = parsedTokens;
  return config;
};

interface ConfigFormProps {
  draft: ConfigDraft;
  onChange: (draft: ConfigDraft) => void;
}

const ConfigForm: React.FC<ConfigFormProps> = ({ draft, onChange }) => {
  const set = (patch: Partial<ConfigDraft>) => onChange({ ...draft, ...patch });
  return (
    <div className="testing-config-grid">
      <div className="form-group">
        <label htmlFor="cfg-model">Summary model (optional)</label>
        <input
          id="cfg-model"
          type="text"
          value={draft.summary_model}
          onChange={(e) => set({ summary_model: e.target.value })}
          placeholder="default"
        />
      </div>
      <div className="form-group">
        <label htmlFor="cfg-limit">Result limit</label>
        <input
          id="cfg-limit"
          type="number"
          value={draft.limit}
          onChange={(e) => set({ limit: e.target.value })}
          placeholder="10"
        />
      </div>
      <div className="form-group">
        <label htmlFor="cfg-temp">Temperature</label>
        <input
          id="cfg-temp"
          type="number"
          step="0.1"
          value={draft.temperature}
          onChange={(e) => set({ temperature: e.target.value })}
          placeholder="0"
        />
      </div>
      <div className="form-group">
        <label htmlFor="cfg-tokens">Max tokens</label>
        <input
          id="cfg-tokens"
          type="number"
          value={draft.max_tokens}
          onChange={(e) => set({ max_tokens: e.target.value })}
          placeholder="1024"
        />
      </div>
      <div className="form-group testing-config-checkbox">
        <label>
          <input
            type="checkbox"
            checked={draft.rerank}
            onChange={(e) => set({ rerank: e.target.checked })}
          />{' '}
          Rerank results
        </label>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Per-case assertion section                                        */
/* ------------------------------------------------------------------ */

// Coerce a stored case_expectations blob into a valid matrix. Legacy drafts
// used the old per-case shape ({caseId: [assertions]}) which has no
// columns/cases keys; those are dropped (incompatible) and start empty.
const toMatrix = (raw: unknown): MatrixValue => {
  if (
    raw &&
    typeof raw === 'object' &&
    Array.isArray((raw as MatrixValue).columns) &&
    typeof (raw as MatrixValue).cases === 'object' &&
    (raw as MatrixValue).cases !== null
  ) {
    const m = raw as MatrixValue;
    return { columns: m.columns, cases: m.cases };
  }
  return { columns: [], cases: {} };
};

// Ensure every displayed case has an explicit state before saving: cases the
// user never touched default to active (so they run) with all columns padded.
// Unlisted cases are treated as inactive by the runner, so this materialises
// the editor's visible defaults into the persisted matrix.
const normalizeMatrix = (matrix: MatrixValue, caseList: TestCase[]): MatrixValue => {
  const ncols = matrix.columns.length;
  const cases: Record<string, CaseRowState> = {};
  caseList.forEach((c) => {
    const prev = matrix.cases[c.id];
    cases[c.id] = {
      active: prev ? prev.active : true,
      cols: Array.from({ length: ncols }, (_, i) => Boolean(prev?.cols?.[i])),
    };
  });
  return { columns: matrix.columns, cases };
};

/* ------------------------------------------------------------------ */
/*  Main editor                                                       */
/* ------------------------------------------------------------------ */

const ExperimentEditor: React.FC<ExperimentEditorProps> = ({
  experiment,
  initialDatasetId,
  onBack,
  onSaved,
}) => {
  const isEdit = Boolean(experiment);

  const [datasets, setDatasets] = useState<TestDataset[]>([]);
  const [name, setName] = useState(experiment?.name || '');
  const [datasetId, setDatasetId] = useState<string>(
    experiment?.dataset_id || initialDatasetId || '',
  );
  const [config, setConfig] = useState<ConfigDraft>(configToDraft(experiment?.config));
  const [matrix, setMatrix] = useState<MatrixValue>(
    toMatrix(experiment?.case_expectations),
  );

  const [cases, setCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [casesLoading, setCasesLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const selectedDataset = datasets.find((d) => d.id === datasetId) || null;

  // Load datasets for the dropdown.
  const fetchDatasets = useCallback(async () => {
    try {
      const resp = await axios.get<TestDataset[]>(`${API_BASE_URL}/testing/datasets`);
      setDatasets(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load datasets');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDatasets();
  }, [fetchDatasets]);

  // Load the cases for the currently-selected dataset.
  const fetchCases = useCallback(async (id: string) => {
    if (!id) {
      setCases([]);
      return;
    }
    setCasesLoading(true);
    try {
      const resp = await axios.get<TestCase[]>(
        `${API_BASE_URL}/testing/datasets/${id}/cases`,
      );
      setCases(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load test cases');
      setCases([]);
    } finally {
      setCasesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCases(datasetId);
  }, [datasetId, fetchCases]);

  const handleDatasetChange = (id: string) => {
    if (id !== datasetId) {
      // Switching dataset invalidates the assertion matrix (different cases).
      setMatrix({ columns: [], cases: {} });
    }
    setDatasetId(id);
  };

  const buildBody = () => ({
    dataset_id: datasetId,
    name: name.trim(),
    config: draftToConfig(config),
    case_expectations: normalizeMatrix(matrix, cases),
  });

  // Save the draft (POST for new, PUT for existing). Returns the experiment id.
  const save = async (): Promise<string | null> => {
    if (!name.trim()) {
      setError('Experiment name is required');
      return null;
    }
    if (!datasetId) {
      setError('Please select a dataset');
      return null;
    }
    setSaving(true);
    setError('');
    try {
      if (isEdit && experiment) {
        await axios.put(`${API_BASE_URL}/testing/experiments/${experiment.id}`, {
          name: name.trim(),
          config: draftToConfig(config),
          case_expectations: normalizeMatrix(matrix, cases),
        });
        return experiment.id;
      }
      const resp = await axios.post<TestExperiment>(
        `${API_BASE_URL}/testing/experiments`,
        buildBody(),
      );
      return resp.data.id;
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save experiment');
      return null;
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    const id = await save();
    if (id) onSaved(id);
  };

  if (loading) return <div className="admin-loading">Loading...</div>;

  return (
    <div className="admin-section testing-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="testing-editor-header">
        <button className="btn-sm" onClick={onBack}>&larr; Back to experiments</button>
        <div className="testing-editor-title">
          <h3 style={{ margin: 0 }}>{isEdit ? 'Edit experiment' : 'New experiment'}</h3>
        </div>
      </div>

      <div className="form-group">
        <label htmlFor="exp-name">Experiment name</label>
        <input
          id="exp-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Baseline run"
        />
      </div>

      <div className="form-group">
        <label htmlFor="exp-dataset">Dataset</label>
        <select
          id="exp-dataset"
          value={datasetId}
          onChange={(e) => handleDatasetChange(e.target.value)}
          disabled={isEdit}
        >
          <option value="">Select a dataset...</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.capability} · {d.data_source})
            </option>
          ))}
        </select>
      </div>

      <div className="admin-section" style={{ marginTop: 0 }}>
        <h4>Run configuration</h4>
        <ConfigForm draft={config} onChange={setConfig} />
      </div>

      <div className="admin-section" style={{ marginTop: 0 }}>
        <h4>Assertions per test case</h4>
        <p className="text-muted" style={{ marginTop: 0 }}>
          Toggle a row to enable/disable a case; add assertion columns and use a
          column&apos;s header checkbox to apply it to all cases. Only active cases and
          checked assertions are run.
        </p>
        {!selectedDataset && (
          <p className="text-muted">Select a dataset to define assertions for its cases.</p>
        )}
        {selectedDataset && casesLoading && (
          <div className="admin-loading">Loading cases...</div>
        )}
        {selectedDataset && !casesLoading && (
          <AssertionMatrix
            capability={selectedDataset.capability}
            cases={cases}
            value={matrix}
            onChange={setMatrix}
          />
        )}
      </div>

      <div className="testing-case-editor-actions">
        <button className="btn-sm btn-cancel" onClick={onBack} disabled={saving}>
          Cancel
        </button>
        <button className="btn-sm btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      <p className="text-muted" style={{ marginTop: '0.5rem' }}>
        Run this experiment from the Experiments table once saved.
      </p>
    </div>
  );
};

export default ExperimentEditor;
