import React, { useRef, useState } from 'react';
import { parseQaCsv, SAMPLE_QA_CSV, QaCsvRow } from './csv';
import { DEFAULT_THRESHOLD, importDatasetWithExperiment } from './experimentImport';

interface CreateDatasetWithExperimentModalProps {
  onCreated: () => void;
  onCancel: () => void;
}

const downloadSampleCsv = () => {
  const blob = new Blob([SAMPLE_QA_CSV], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'qa-experiment-sample.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

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
  const [dataSource, setDataSource] = useState('');
  const [experimentName, setExperimentName] = useState('');
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [fileName, setFileName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement | null>(null);

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
        dataSource,
        experimentName,
        threshold,
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
            Upload a CSV with a <strong>Question</strong> column and an{' '}
            <strong>Unpacking Question / Probing</strong> column (the expected
            answer). This creates an AI-summary dataset of the questions and a
            draft experiment with one LLM-judge assertion per row, each judged
            against that row&apos;s expected answer.
          </p>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="cde-name">Dataset name</label>
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
            <div className="form-group">
              <label htmlFor="cde-exp-name">Experiment name (optional)</label>
              <input
                id="cde-exp-name"
                type="text"
                value={experimentName}
                onChange={(e) => setExperimentName(e.target.value)}
                placeholder="Defaults to “<dataset> — LLM judge”"
              />
            </div>
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
                <button
                  type="button"
                  className="testing-raw-toggle"
                  onClick={downloadSampleCsv}
                >
                  sample format
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
