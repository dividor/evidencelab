import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestDataset, TestExperiment } from '../../../types/testing';
import { formatMs, formatPercent, formatScore, formatTimestamp } from './testingFormat';

interface ExperimentListProps {
  dataset?: TestDataset | null; // when set, scopes to one dataset and offers back
  onOpen: (experiment: TestExperiment) => void;
  onBack?: () => void;
}

const POLL_INTERVAL_MS = 2000;

const isActive = (e: TestExperiment): boolean =>
  e.status === 'pending' || e.status === 'running';

const ExperimentList: React.FC<ExperimentListProps> = ({ dataset, onOpen, onBack }) => {
  const [experiments, setExperiments] = useState<TestExperiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
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

  useEffect(() => {
    fetchExperiments();
  }, [fetchExperiments]);

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
        <button
          className="btn-sm"
          style={{ marginLeft: 'auto' }}
          onClick={fetchExperiments}
        >
          Refresh
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Pass rate</th>
            <th>Mean score</th>
            <th>Duration</th>
            <th>Created</th>
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
                <td>
                  <span className={`testing-status testing-status-${exp.status}`}>
                    {exp.status}
                  </span>
                </td>
                <td>{formatPercent(stats?.pass_rate)}</td>
                <td>{formatScore(stats?.mean_score)}</td>
                <td>{formatMs(stats?.duration_ms)}</td>
                <td>{formatTimestamp(exp.created_at)}</td>
              </tr>
            );
          })}
          {experiments.length === 0 && (
            <tr>
              <td colSpan={6} className="text-muted">No experiments yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

export default ExperimentList;
