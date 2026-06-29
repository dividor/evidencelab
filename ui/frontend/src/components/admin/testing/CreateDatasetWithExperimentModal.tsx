import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestCapability } from '../../../types/testing';
import { parseQaCsv, QaCsvRow } from './csv';
import { DEFAULT_THRESHOLD, importDatasetWithExperiment } from './experimentImport';
import {
  ConfigDraft,
  ConfigForm,
  GroupOption,
  configToDraft,
  draftToConfig,
} from './ExperimentEditor';

interface CreateDatasetWithExperimentModalProps {
  onCreated: () => void;
  onCancel: () => void;
}

const CAPABILITIES: TestCapability[] = ['search', 'ai_summary'];

const clampThreshold = (value: number): number => {
  if (Number.isNaN(value)) return DEFAULT_THRESHOLD;
  return Math.min(1, Math.max(0, value));
};

// Read + parse the chosen CSV into rows; returns an error string instead of
// throwing so the caller can surface it inline.
const readRows = async (
  file: File,
): Promise<{ rows: QaCsvRow[]; error: string }> => {
  let rows: QaCsvRow[];
  try {
    rows = parseQaCsv(await file.arrayBuffer());
  } catch {
    return { rows: [], error: 'Could not parse the CSV file.' };
  }
  if (rows.length === 0) {
    return { rows: [], error: 'No rows with a "Question" column were found.' };
  }
  return { rows, error: '' };
};

const CreateDatasetWithExperimentModal: React.FC<
  CreateDatasetWithExperimentModalProps
> = ({ onCreated, onCancel }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [capability, setCapability] = useState<TestCapability>('ai_summary');
  const [dataSource, setDataSource] = useState('');
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [config, setConfig] = useState<ConfigDraft>(configToDraft(null));
  const [modelCombos, setModelCombos] = useState<string[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [fileName, setFileName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Load model combos filtered to the entered data source (mirroring the
  // experiment editor + the search UI) so only combos actually configured for
  // this environment appear — not every combo in config.json. Re-fetches as the
  // data source changes; defaults to the first combo, which also auto-selects it
  // when the data source has only one configured combo.
  useEffect(() => {
    const source = dataSource.trim();
    if (!source) {
      setModelCombos([]);
      return undefined;
    }
    let cancelled = false;
    const params = `?data_source=${encodeURIComponent(source)}`;
    axios
      .get<Record<string, unknown>>(`${API_BASE_URL}/config/model-combos${params}`)
      .then((resp) => {
        if (cancelled) return;
        const names = Object.keys(resp.data || {});
        setModelCombos(names);
        setConfig((c) =>
          c.model_combo && names.includes(c.model_combo)
            ? c
            : { ...c, model_combo: names[0] || '' },
        );
      })
      .catch(() => {
        // Non-fatal: the combo dropdown stays empty if config can't load.
      });
    return () => {
      cancelled = true;
    };
  }, [dataSource]);

  // Load user groups for the "Run as group" dropdown.
  useEffect(() => {
    let cancelled = false;
    axios
      .get<GroupOption[]>(`${API_BASE_URL}/groups/`)
      .then((resp) => {
        if (!cancelled) setGroups(resp.data || []);
      })
      .catch(() => {
        // Non-fatal: groups may be unavailable (user module off) — dropdown empty.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError('Please choose a CSV file to upload.');
      return;
    }
    const { rows, error: readError } = await readRows(file);
    if (readError) {
      setError(readError);
      return;
    }
    setBusy(true);
    try {
      await importDatasetWithExperiment({
        name,
        description,
        capability,
        dataSource,
        threshold,
        config: draftToConfig(config),
        rows,
      });
      onCreated();
    } catch (err: any) {
      setError(
        err.response?.data?.detail
          || 'Failed to create the dataset and experiment.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-content login-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h3>Create Dataset + Experiment</h3>
          <button className="modal-close" onClick={onCancel}>&times;</button>
        </div>
        <div className="modal-body">
          {error && <div className="auth-error">{error}</div>}
          <p className="text-muted" style={{ marginTop: 0 }}>
            Upload dataset and expectation to create experiment. See the parent
            page for a link to a sample sheet.
          </p>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="cde-name">Name</label>
              <input
                id="cde-name"
                type="text"
                required
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My evaluation set"
              />
            </div>
            <div className="form-group">
              <label htmlFor="cde-desc">Description (optional)</label>
              <input
                id="cde-desc"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this dataset tests"
              />
            </div>
            <div className="form-group">
              <label htmlFor="cde-capability">What to test</label>
              <select
                id="cde-capability"
                value={capability}
                onChange={(e) => setCapability(e.target.value as TestCapability)}
              >
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <small className="text-muted">
                The expectation column builds an LLM-judge assertion, which
                evaluates the AI summary — choose <code>ai_summary</code> for it
                to apply.
              </small>
            </div>
            <div className="form-group">
              <label htmlFor="cde-source">Data source</label>
              <input
                id="cde-source"
                type="text"
                required
                value={dataSource}
                onChange={(e) => setDataSource(e.target.value)}
                placeholder="e.g. uneg"
              />
            </div>
            <ConfigForm
              draft={config}
              modelCombos={modelCombos}
              groups={groups}
              onChange={setConfig}
              showHints={false}
            />
            <div className="form-group">
              <label htmlFor="cde-threshold">Judge threshold (0–1)</label>
              <input
                id="cde-threshold"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(clampThreshold(e.target.valueAsNumber))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="cde-file">Questions CSV</label>
              <div className="testing-upload-group">
                <button
                  type="button"
                  className="btn-sm"
                  onClick={() => fileRef.current?.click()}
                >
                  {fileName || 'Choose CSV…'}
                </button>
              </div>
              <input
                id="cde-file"
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                style={{ display: 'none' }}
                onChange={(e) => setFileName(e.target.files?.[0]?.name || '')}
              />
            </div>
            <button type="submit" className="auth-submit" disabled={busy}>
              {busy ? 'Creating…' : 'Create Dataset + Experiment'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default CreateDatasetWithExperimentModal;
