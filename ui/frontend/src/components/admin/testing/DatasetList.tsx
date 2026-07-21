import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestCapability, TestDataset } from '../../../types/testing';
import ConfirmModal from '../ConfirmModal';
import CreateDatasetWithExperimentModal from './CreateDatasetWithExperimentModal';
import { formatTimestamp } from './testingFormat';
import { SAMPLE_DATASET_CSV, SAMPLE_QA_CSV } from './csv';

const CAPABILITIES: TestCapability[] = ['search', 'ai_summary'];

const downloadCsv = (content: string, filename: string) => {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

/* ------------------------------------------------------------------ */
/*  Create-dataset modal                                              */
/* ------------------------------------------------------------------ */

interface CreateDatasetModalProps {
  onCreated: () => void;
  onCancel: () => void;
}

const CreateDatasetModal: React.FC<CreateDatasetModalProps> = ({ onCreated, onCancel }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [capability, setCapability] = useState<TestCapability>('search');
  const [dataSource, setDataSource] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setCreating(true);
    try {
      await axios.post(`${API_BASE_URL}/testing/datasets`, {
        name,
        description: description || undefined,
        capability,
        data_source: dataSource,
      });
      onCreated();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create dataset');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Create Dataset</h3>
          <button className="modal-close" onClick={onCancel}>&times;</button>
        </div>
        <div className="modal-body">
          {error && <div className="auth-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="ds-name">Name</label>
              <input
                id="ds-name"
                type="text"
                required
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My evaluation set"
              />
            </div>
            <div className="form-group">
              <label htmlFor="ds-desc">Description (optional)</label>
              <input
                id="ds-desc"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this dataset tests"
              />
            </div>
            <div className="form-group">
              <label htmlFor="ds-capability">Capability</label>
              <select
                id="ds-capability"
                value={capability}
                onChange={(e) => setCapability(e.target.value as TestCapability)}
              >
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="ds-source">Data source</label>
              <input
                id="ds-source"
                type="text"
                required
                value={dataSource}
                onChange={(e) => setDataSource(e.target.value)}
                placeholder="e.g. uneg"
              />
            </div>
            <button type="submit" className="auth-submit" disabled={creating}>
              {creating ? 'Creating...' : 'Create Dataset'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Dataset list                                                      */
/* ------------------------------------------------------------------ */

interface DatasetListProps {
  onOpen: (dataset: TestDataset) => void;
}

const DatasetList: React.FC<DatasetListProps> = ({ onOpen }) => {
  const [datasets, setDatasets] = useState<TestDataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [capabilityFilter, setCapabilityFilter] = useState<'' | TestCapability>('');
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TestDataset | null>(null);

  const fetchDatasets = useCallback(async () => {
    try {
      const resp = await axios.get<TestDataset[]>(`${API_BASE_URL}/testing/datasets`, {
        params: capabilityFilter ? { capability: capabilityFilter } : undefined,
      });
      setDatasets(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load datasets');
    } finally {
      setLoading(false);
    }
  }, [capabilityFilter]);

  useEffect(() => {
    fetchDatasets();
  }, [fetchDatasets]);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await axios.delete(`${API_BASE_URL}/testing/datasets/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchDatasets();
    } catch (err: any) {
      setDeleteTarget(null);
      setError(err.response?.data?.detail || 'Failed to delete dataset');
    }
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
      <div className="testing-controls">
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="ds-filter">Capability</label>
          <select
            id="ds-filter"
            value={capabilityFilter}
            onChange={(e) => setCapabilityFilter(e.target.value as '' | TestCapability)}
          >
            <option value="">All</option>
            {CAPABILITIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <p className="text-muted" style={{ margin: 0 }}>
          {datasets.length} dataset{datasets.length !== 1 ? 's' : ''}
        </p>
        <div
          className="testing-dataset-actions"
          style={{ marginLeft: 'auto' }}
        >
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}
          >
            <button
              className="btn-sm btn-primary"
              onClick={() => setShowCreate(true)}
            >
              + Create Dataset
            </button>
            <button
              type="button"
              className="testing-raw-toggle"
              onClick={() =>
                downloadCsv(SAMPLE_DATASET_CSV, 'test-cases-sample.csv')
              }
            >
              sample format
            </button>
          </div>
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}
          >
            <button
              className="btn-sm btn-primary"
              onClick={() => setShowImport(true)}
            >
              + Create Dataset and Experiment
            </button>
            <button
              type="button"
              className="testing-raw-toggle"
              onClick={() =>
                downloadCsv(SAMPLE_QA_CSV, 'qa-experiment-sample.csv')
              }
            >
              sample format
            </button>
          </div>
        </div>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Capability</th>
            <th>Data source</th>
            <th># Cases</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((ds) => (
            <tr key={ds.id} className="testing-clickable-row" onClick={() => onOpen(ds)}>
              <td>{ds.name}</td>
              <td>{ds.capability}</td>
              <td>{ds.data_source}</td>
              <td>{ds.num_cases ?? 0}</td>
              <td>{formatTimestamp(ds.created_at)}</td>
              <td onClick={(e) => e.stopPropagation()}>
                <button
                  className="btn-sm btn-danger"
                  onClick={() => setDeleteTarget(ds)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {datasets.length === 0 && (
            <tr>
              <td colSpan={6} className="text-muted">No datasets yet.</td>
            </tr>
          )}
        </tbody>
      </table>

      {deleteTarget && (
        <ConfirmModal
          title="Delete Dataset"
          message={`Permanently delete "${deleteTarget.name}" and all its test cases and experiments? This cannot be undone.`}
          confirmLabel="Delete Dataset"
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {showCreate && (
        <CreateDatasetModal
          onCreated={() => {
            setShowCreate(false);
            fetchDatasets();
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {showImport && (
        <CreateDatasetWithExperimentModal
          onCreated={() => {
            setShowImport(false);
            fetchDatasets();
          }}
          onCancel={() => setShowImport(false)}
        />
      )}
    </div>
  );
};

export default DatasetList;
