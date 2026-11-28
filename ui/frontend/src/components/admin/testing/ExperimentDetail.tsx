import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type {
  ExperimentDetail as ExperimentDetailType,
  TestCase,
  TestRun,
} from '../../../types/testing';
import {
  formatMs,
  formatPercent,
  formatScore,
  formatTimestamp,
} from './testingFormat';
import RunPassRateChart from './RunPassRateChart';
import { RunStats, RunProgressBar } from './BriefScoreStats';
import { RemainingSections, ResultRow, ResultTable } from './ResultTable';
import { runConfigHeadline, runConfigRows } from './runConfig';

interface ExperimentDetailProps {
  experimentId: string;
  onBack: () => void;
  onEdit: (experiment: ExperimentDetailType) => void;
}

const POLL_INTERVAL_MS = 2000;

const isActive = (status?: string): boolean =>
  status === 'pending' || status === 'running';

/* ------------------------------------------------------------------ */
/*  One run: collapsible header + its per-case results                */
/* ------------------------------------------------------------------ */

const passRateLevel = (rate?: number | null): string => {
  if (rate === null || rate === undefined) return 'none';
  if (rate >= 1) return 'good';
  if (rate > 0) return 'warn';
  return 'bad';
};

/* ------------------------------------------------------------------ */
/*  Per-run configuration — what the run executed with, vs. the previous run */
/* ------------------------------------------------------------------ */

const RunConfigPanel: React.FC<{ run: TestRun; previous?: TestRun }> = ({ run, previous }) => {
  const [open, setOpen] = useState(false);
  const rows = runConfigRows(run.config, previous?.config);
  if (rows.length === 0) {
    return (
      <p className="text-muted testing-run-config-missing">
        Configuration not recorded (run predates configuration tracking).
      </p>
    );
  }
  const changed = rows.filter((r) => r.changed).length;
  const sections = Array.from(new Set(rows.map((r) => r.section)));
  return (
    <div className="testing-run-config">
      <button
        type="button"
        className="testing-collapse-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="testing-collapse-caret" aria-hidden>{open ? '▾' : '▸'}</span>
        <span className="testing-case-label">Configuration</span>
        <span className="testing-run-config-headline">{runConfigHeadline(run.config)}</span>
        {previous && (
          <span className={`testing-run-config-diff${changed ? ' testing-run-config-diff--changed' : ''}`}>
            {changed
              ? `${changed} setting${changed === 1 ? '' : 's'} changed vs run #${previous.run_number}`
              : `same as run #${previous.run_number}`}
          </span>
        )}
      </button>
      {open && (
        <div className="testing-run-config-sections">
          {sections.map((section) => (
            <dl key={section} className="testing-run-config-section">
              <div className="testing-run-config-section-title">{section}</div>
              {rows.filter((r) => r.section === section).map((r) => (
                <div
                  key={r.key}
                  className={`testing-run-config-row${r.changed ? ' testing-run-config-row--changed' : ''}`}
                  title={r.changed && previous ? `Changed vs run #${previous.run_number}` : undefined}
                >
                  <dt>{r.label}</dt>
                  <dd>{r.value}</dd>
                </div>
              ))}
            </dl>
          ))}
        </div>
      )}
    </div>
  );
};

const RunSection: React.FC<{
  run: TestRun;
  previous?: TestRun;
  caseInputs: Record<string, Record<string, unknown>>;
  defaultOpen: boolean;
  isLatest: boolean;
}> = ({ run, previous, caseInputs, defaultOpen, isLatest }) => {
  const [open, setOpen] = useState(defaultOpen);
  const stats = run.summary_stats;
  const active = isActive(run.status);
  const results = run.results || [];
  const level = passRateLevel(stats?.pass_rate);
  const isBrief = run.config?.capability === 'brief';
  const unit = isBrief ? 'section' : 'case';
  return (
    <div className={`testing-run${isLatest ? ' testing-run--latest' : ''}`}>
      <button
        type="button"
        className={`testing-run-header${open ? ' testing-run-header--open' : ''}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="testing-run-caret" aria-hidden><span className="testing-disclosure-arrow" /></span>
        <span className="testing-run-number">Run&nbsp;#{run.run_number}</span>
        <span
          className={`testing-status testing-status-${run.status} testing-run-status`}
        >
          {run.status}
        </span>
        {isLatest && <span className="testing-run-latest">Latest</span>}
        {active && stats?.progress ? (
          <span className="testing-run-metrics">
            <span className="testing-run-metric">
              <strong>
                {stats.progress.completed}
                <span className="testing-run-progress-of">/{stats.progress.total}</span>
              </strong>
              <span className="testing-run-metric-label">{unit}s</span>
            </span>
          </span>
        ) : (
          <span className="testing-run-metrics">
            <span className="testing-run-metric">
              <strong className={`testing-passrate testing-passrate--${level}`}>
                {formatPercent(stats?.pass_rate)}
              </strong>
              <span className="testing-run-metric-label">pass</span>
            </span>
            <span className="testing-run-metric">
              <strong>{formatScore(stats?.mean_score)}</strong>
              <span className="testing-run-metric-label">Mean Total Score</span>
            </span>
            <span className="testing-run-metric">
              <strong>{formatMs(stats?.duration_ms)}</strong>
              <span className="testing-run-metric-label">dur</span>
            </span>
          </span>
        )}
        <span className="testing-run-time">
          {formatTimestamp(run.finished_at || run.started_at)}
        </span>
      </button>
      {open && (
        <div className="testing-run-body">
          {stats?.error && <div className="auth-error">Run error: {stats.error}</div>}
          {active && <RunProgressBar progress={stats?.progress} unit={unit} />}
          <RunStats stats={stats} brief={isBrief} total={stats?.total} passed={stats?.passed} failed={stats?.failed}
            errored={stats?.errored} started={run.started_at} finished={run.finished_at} />
          <RunConfigPanel run={run} previous={previous} />
          <ResultTable brief={isBrief} heading={isBrief ? 'Section and template' : 'Case'}>
              {results.map((r) => (
                <ResultRow key={r.id} brief={isBrief} result={r} input={r.test_case_id ? caseInputs[r.test_case_id] : undefined} />
              ))}
              <RemainingSections sections={stats?.progress?.remaining_sections} />
              {results.length === 0 && !stats?.progress?.remaining_sections?.length && (
                <tr>
                  <td colSpan={isBrief ? 8 : 6} className="text-muted">
                    {active ? 'Running — results appear here as each case finishes…' : 'No results.'}
                  </td>
                </tr>
              )}
          </ResultTable>
        </div>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Run config shown as friendly badges (group name + model combo)    */
/* ------------------------------------------------------------------ */

const ConfigBadges: React.FC<{
  config?: Record<string, unknown> | null;
  groups: Array<{ id: string; name: string }>;
}> = ({ config, groups }) => {
  const cfg = config || {};
  const combo = typeof cfg.model_combo === 'string' ? cfg.model_combo : '';
  const groupId = typeof cfg.group_id === 'string' ? cfg.group_id : '';
  const groupName = groupId
    ? groups.find((g) => g.id === groupId)?.name || `${groupId.slice(0, 8)}…`
    : '';
  if (!combo && !groupName) return null;
  return (
    <div className="testing-config-badges">
      {combo && (
        <span className="testing-config-badge">
          <span className="testing-config-badge-label">Model</span>
          {combo}
        </span>
      )}
      {groupName && (
        <span className="testing-config-badge">
          <span className="testing-config-badge-label">Group</span>
          {groupName}
        </span>
      )}
    </div>
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
  const [groups, setGroups] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Group id -> name, so the config can show the group name instead of a UUID.
  useEffect(() => {
    let cancelled = false;
    axios
      .get<Array<{ id: string; name: string }>>(`${API_BASE_URL}/groups/`)
      .then((resp) => {
        if (!cancelled) setGroups(resp.data || []);
      })
      .catch(() => {
        // Non-fatal: fall back to showing the group id.
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  if (loading) return <div className="admin-loading">Loading...</div>;
  if (!detail) {
    return (
      <div className="admin-section testing-section">
        <button className="btn-sm" onClick={onBack}>&larr; Back</button>
        <div className="auth-error">{error || 'Experiment not found'}</div>
      </div>
    );
  }

  const runs = detail.runs || [];
  const active = isActive(detail.status);

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
          <div className="testing-detail-titlerow">
            <h3 style={{ margin: 0 }}>{detail.name}</h3>
            <ConfigBadges config={detail.config} groups={groups} />
          </div>
        </div>
        <div className="testing-editor-header-actions" style={{ marginLeft: 'auto' }}>
          {!active && (
            <button className="btn-sm" onClick={() => onEdit(detail)}>
              Edit
            </button>
          )}
        </div>
      </div>

      <h4 style={{ marginBottom: '0.5rem' }}>Runs ({runs.length})</h4>
      {runs.length === 0 ? (
        <p className="text-muted">
          No runs yet. Use <strong>Run</strong> in the experiments table to run this
          experiment.
        </p>
      ) : (
        <>
          <RunPassRateChart runs={runs} />
          <div className="testing-runs">
            {runs.map((run, idx) => (
              <RunSection
                key={run.id}
                run={run}
                previous={runs[idx + 1]}
                caseInputs={caseInputs}
                defaultOpen={idx === 0}
                isLatest={idx === 0}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default ExperimentDetail;
