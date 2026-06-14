import React, { useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';

interface RunExperimentModalProps {
  datasetId: string;
  onLaunched: () => void;
  onCancel: () => void;
}

const DEFAULT_CONFIG = `{
  "summary_model": null,
  "limit": 10,
  "rerank": false,
  "temperature": 0,
  "max_tokens": 1024,
  "enable_llm_judge": false
}`;

const RunExperimentModal: React.FC<RunExperimentModalProps> = ({
  datasetId,
  onLaunched,
  onCancel,
}) => {
  const [name, setName] = useState('');
  const [configJson, setConfigJson] = useState(DEFAULT_CONFIG);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    let config: Record<string, unknown> | undefined;
    if (configJson.trim()) {
      try {
        const parsed = JSON.parse(configJson);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('Config must be a JSON object');
        }
        config = parsed as Record<string, unknown>;
      } catch (err: any) {
        setError(err.message || 'Invalid config JSON');
        return;
      }
    }

    setLaunching(true);
    try {
      await axios.post(`${API_BASE_URL}/testing/experiments`, {
        dataset_id: datasetId,
        name,
        config,
      });
      onLaunched();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to launch experiment');
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Run Experiment</h3>
          <button className="modal-close" onClick={onCancel}>&times;</button>
        </div>
        <div className="modal-body">
          {error && <div className="auth-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="exp-name">Experiment name</label>
              <input
                id="exp-name"
                type="text"
                required
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Baseline run"
              />
            </div>
            <div className="form-group">
              <label htmlFor="exp-config">Config (JSON object)</label>
              <textarea
                id="exp-config"
                className="testing-json-textarea"
                value={configJson}
                onChange={(e) => setConfigJson(e.target.value)}
                rows={8}
              />
            </div>
            <button type="submit" className="auth-submit" disabled={launching}>
              {launching ? 'Launching...' : 'Launch Experiment'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default RunExperimentModal;
