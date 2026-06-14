import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type {
  AssertionResult,
  ExperimentDetail as ExperimentDetailType,
  TestCase,
  TestResult,
} from '../../../types/testing';
import {
  formatMs,
  formatPercent,
  formatScore,
  formatTimestamp,
  prettyJson,
} from './testingFormat';

interface ExperimentDetailProps {
  experimentId: string;
  onBack: () => void;
  onEdit: (experiment: ExperimentDetailType) => void;
}

const POLL_INTERVAL_MS = 2000;

const isActive = (status?: string): boolean =>
  status === 'pending' || status === 'running';

/* ------------------------------------------------------------------ */
/*  Summary header — every number labelled with its unit              */
/* ------------------------------------------------------------------ */

const SummaryHeader: React.FC<{ detail: ExperimentDetailType }> = ({ detail }) => {
  const stats = detail.summary_stats;
  return (
    <div className="testing-summary-header">
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Status</span>
        <span className={`testing-status testing-status-${detail.status}`}>
          {detail.status}
        </span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Pass rate</span>
        <span>{formatPercent(stats?.pass_rate)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Mean score</span>
        <span>{formatScore(stats?.mean_score)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Total cases</span>
        <span>{stats?.total ?? '-'}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Passed</span>
        <span>{stats?.passed ?? '-'}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Failed</span>
        <span>{stats?.failed ?? '-'}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Errored</span>
        <span>{stats?.errored ?? '-'}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Duration (ms)</span>
        <span>{formatMs(stats?.duration_ms)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Started</span>
        <span>{formatTimestamp(detail.started_at)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Finished</span>
        <span>{formatTimestamp(detail.finished_at)}</span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Per-assertion result row                                          */
/* ------------------------------------------------------------------ */

const AssertionResultRow: React.FC<{ result: AssertionResult }> = ({ result }) => (
  <div className="testing-assertion-result">
    <span
      className={`testing-badge testing-badge-${result.passed ? 'pass' : 'fail'}`}
    >
      {result.passed ? 'pass' : 'fail'}
    </span>
    <span className="testing-assertion-result-type">{result.type}</span>
    {result.score !== undefined && (
      <span className="testing-assertion-result-score">
        score: {formatScore(result.score)}
      </span>
    )}
    <span className="testing-assertion-result-message">{result.message}</span>
  </div>
);

/* ------------------------------------------------------------------ */
/*  Expandable result row                                             */
/* ------------------------------------------------------------------ */

const ResultRow: React.FC<{ result: TestResult; input?: Record<string, unknown> }> = ({
  result,
  input,
}) => {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <tr className="testing-clickable-row" onClick={() => setExpanded((v) => !v)}>
        <td>{expanded ? '▾' : '▸'}</td>
        <td>
          <span className={`testing-badge testing-badge-${result.status}`}>
            {result.status}
          </span>
        </td>
        <td>{formatScore(result.score)}</td>
        <td>{formatMs(result.latency_ms)}</td>
        <td className="testing-result-error">{result.error_message || ''}</td>
      </tr>
      {expanded && (
        <tr className="testing-result-detail-row">
          <td colSpan={5}>
            <div className="testing-result-detail">
              <div className="testing-case-block">
                <span className="testing-case-label">Case input</span>
                <pre className="testing-pre">{prettyJson(input ?? {})}</pre>
              </div>
              <div className="testing-case-block">
                <span className="testing-case-label">Assertions</span>
                {(result.assertion_results || []).map((ar, i) => (
                  <AssertionResultRow key={i} result={ar} />
                ))}
                {(result.assertion_results || []).length === 0 && (
                  <p className="text-muted" style={{ margin: 0 }}>No assertion results.</p>
                )}
              </div>
              <div className="testing-case-block">
                <span className="testing-case-label">Raw actual output</span>
                <pre className="testing-pre testing-pre-scroll">
                  {prettyJson(result.actual_output)}
                </pre>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/*  Main detail view                                                  */
/* ------------------------------------------------------------------ */

const ExperimentDetail: React.FC<ExperimentDetailProps> = ({
  experimentId,
  onBack,
  onEdit,
}) => {
  const [detail, setDetail] = useState<ExperimentDetailType | null>(null);
  const [caseInputs, setCaseInputs] = useState<Record<string, Record<string, unknown>>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDetail = useCallback(async () => {
    try {
      const resp = await axios.get<ExperimentDetailType>(
        `${API_BASE_URL}/testing/experiments/${experimentId}`,
      );
      setDetail(resp.data);
      return resp.data;
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load experiment');
      return null;
    } finally {
      setLoading(false);
    }
  }, [experimentId]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  // Fetch the dataset's case inputs (for the expandable detail view).
  useEffect(() => {
    if (!detail?.dataset_id) return;
    let cancelled = false;
    axios
      .get<TestCase[]>(`${API_BASE_URL}/testing/datasets/${detail.dataset_id}/cases`)
      .then((resp) => {
        if (cancelled) return;
        const map: Record<string, Record<string, unknown>> = {};
        resp.data.forEach((c) => {
          map[c.id] = c.input || {};
        });
        setCaseInputs(map);
      })
      .catch(() => {
        // Non-fatal: inputs simply won't be shown.
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.dataset_id]);

  // Poll while pending/running.
  useEffect(() => {
    const active = isActive(detail?.status);
    if (active && timerRef.current === null) {
      timerRef.current = setInterval(fetchDetail, POLL_INTERVAL_MS);
    } else if (!active && timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [detail?.status, fetchDetail]);

  const handleRun = async () => {
    setRunning(true);
    setError('');
    try {
      await axios.post(`${API_BASE_URL}/testing/experiments/${experimentId}/run`);
      await fetchDetail();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to run experiment');
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <div className="admin-loading">Loading...</div>;
  if (!detail) {
    return (
      <div className="admin-section testing-section">
        <button className="btn-sm" onClick={onBack}>&larr; Back</button>
        <div className="auth-error">{error || 'Experiment not found'}</div>
      </div>
    );
  }

  const results = detail.results || [];
  const active = isActive(detail.status);
  const runLabel = detail.status === 'draft' ? 'Run' : 'Re-run';

  return (
    <div className="admin-section testing-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="testing-editor-header">
        <button className="btn-sm" onClick={onBack}>&larr; Back</button>
        <div className="testing-editor-title">
          <h3 style={{ margin: 0 }}>{detail.name}</h3>
          {detail.config && (
            <p className="text-muted" style={{ margin: 0 }}>
              Config: {prettyJson(detail.config)}
            </p>
          )}
        </div>
        <div className="testing-editor-header-actions" style={{ marginLeft: 'auto' }}>
          {detail.status === 'draft' && (
            <button className="btn-sm" onClick={() => onEdit(detail)} disabled={running}>
              Edit draft
            </button>
          )}
          <button
            className="btn-sm btn-primary"
            onClick={handleRun}
            disabled={running || active}
          >
            {running ? 'Starting...' : runLabel}
          </button>
        </div>
      </div>

      {detail.summary_stats?.error && (
        <div className="auth-error">Run error: {detail.summary_stats.error}</div>
      )}

      <SummaryHeader detail={detail} />

      <table className="admin-table">
        <thead>
          <tr>
            <th></th>
            <th>Status</th>
            <th>Score</th>
            <th>Latency (ms)</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <ResultRow key={r.id} result={r} input={caseInputs[r.test_case_id]} />
          ))}
          {results.length === 0 && (
            <tr>
              <td colSpan={5} className="text-muted">
                {active ? 'Running — results will appear shortly...' : 'No results.'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

export default ExperimentDetail;
