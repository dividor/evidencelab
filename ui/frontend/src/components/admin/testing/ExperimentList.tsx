import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestDataset, TestExperiment } from '../../../types/testing';
import { formatMs, formatPercent, formatScore, formatTimestamp } from './testingFormat';
import ConfirmModal from '../ConfirmModal';

interface ExperimentListProps {
  dataset?: TestDataset | null; // when set, scopes to one dataset and offers back
  onOpen: (experiment: TestExperiment) => void;
  onEdit: (experiment: TestExperiment) => void;
  onCreate: () => void;
  onBack?: () => void;
}

const POLL_INTERVAL_MS = 2000;

const isActive = (e: TestExperiment): boolean =>
  e.status === 'pending' || e.status === 'running';

const ExperimentList: React.FC<ExperimentListProps> = ({
  dataset,
  onOpen,
  onEdit,
  onCreate,
  onBack,
}) => {
  const [experiments, setExperiments] = useState<TestExperiment[]>([]);
  const [datasetNames, setDatasetNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TestExperiment | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchExperiments = useCallback(async () => {
    try {
      const resp = await axios.get<TestExperiment[]>(`${API_BASE_URL}/testing/experiments`, {
        params: dataset ? { dataset_id: dataset.id } : undefined,
      });
      setExperiments(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load experiments');
    } finally {
      setLoading(false);
    }
  }, [dataset]);

  const fetchDatasetNames = useCallback(async () => {
    try {
      const resp = await axios.get<TestDataset[]>(`${API_BASE_URL}/testing/datasets`);
      const map: Record<string, string> = {};
      resp.data.forEach((d) => {
        map[d.id] = d.name;
      });
      setDatasetNames(map);
    } catch {
      // Non-fatal: fall back to showing dataset ids.
    }
  }, []);

  useEffect(() => {
    fetchExperiments();
    fetchDatasetNames();
  }, [fetchExperiments, fetchDatasetNames]);

  // Poll while any experiment is still pending/running.
  useEffect(() => {
    const anyActive = experiments.some(isActive);
    if (anyActive && timerRef.current === null) {
      timerRef.current = setInterval(fetchExperiments, POLL_INTERVAL_MS);
    } else if (!anyActive && timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [experiments, fetchExperiments]);

  const handleRun = async (exp: TestExperiment) => {
    setBusyId(exp.id);
    setError('');
    try {
      await axios.post(`${API_BASE_URL}/testing/experiments/${exp.id}/run`);
      await fetchExperiments();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start run');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    setError('');
    try {
      await axios.delete(`${API_BASE_URL}/testing/experiments/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchExperiments();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete experiment');
    } finally {
      setBusyId(null);
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
        {onBack && (
          <button className="btn-sm" onClick={onBack}>&larr; Back</button>
        )}
        <p className="text-muted" style={{ margin: 0 }}>
          {dataset ? `Experiments for "${dataset.name}"` : 'All experiments'} ·{' '}
          {experiments.length} total
        </p>
        <button className="btn-sm" onClick={fetchExperiments}>
          Refresh
        </button>
        <button
          className="btn-sm btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={onCreate}
        >
          + New Experiment
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Dataset</th>
            <th>Status</th>
            <th>Pass rate</th>
            <th>Mean score</th>
            <th>Duration (ms)</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {experiments.map((exp) => {
            const stats = exp.summary_stats;
            return (
              <tr
                key={exp.id}
                className="testing-clickable-row"
                onClick={() => onOpen(exp)}
              >
                <td>{exp.name}</td>
                <td>{datasetNames[exp.dataset_id] || exp.dataset_id.slice(0, 8)}</td>
                <td>
                  <span className={`testing-status testing-status-${exp.status}`}>
                    {exp.status}
                  </span>
                </td>
                <td>{formatPercent(stats?.pass_rate)}</td>
                <td>{formatScore(stats?.mean_score)}</td>
                <td>{formatMs(stats?.duration_ms)}</td>
                <td>{formatTimestamp(exp.created_at)}</td>
                <td onClick={(e) => e.stopPropagation()} className="testing-row-actions">
                  <button
                    className="btn-sm btn-primary"
                    onClick={() => handleRun(exp)}
                    disabled={busyId === exp.id || isActive(exp)}
                  >
                    {busyId === exp.id ? 'Starting...' : 'Run'}
                  </button>
                  <button
                    className="btn-sm"
                    onClick={() => onEdit(exp)}
                    disabled={busyId === exp.id || isActive(exp)}
                  >
                    Edit
                  </button>
                  <button
                    className="btn-sm btn-danger"
                    onClick={() => setDeleteTarget(exp)}
                    disabled={busyId === exp.id || isActive(exp)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            );
          })}
          {experiments.length === 0 && (
            <tr>
              <td colSpan={8} className="text-muted">No experiments yet.</td>
            </tr>
          )}
        </tbody>
      </table>

      {deleteTarget && (
        <ConfirmModal
          title="Delete experiment"
          message={`Delete experiment "${deleteTarget.name}" and all its results? This cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};

export default ExperimentList;
