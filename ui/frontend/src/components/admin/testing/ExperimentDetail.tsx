import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type {
  AssertionResult,
  ExperimentDetail as ExperimentDetailType,
  RunProgress,
  TestCase,
  TestResult,
  TestRun,
} from '../../../types/testing';
import {
  formatMs,
  formatPercent,
  formatScore,
  formatTimestamp,
  prettyJson,
} from './testingFormat';
import RunPassRateChart from './RunPassRateChart';

interface ExperimentDetailProps {
  experimentId: string;
  onBack: () => void;
  onEdit: (experiment: ExperimentDetailType) => void;
}

const POLL_INTERVAL_MS = 2000;

const isActive = (status?: string): boolean =>
  status === 'pending' || status === 'running';

/* ------------------------------------------------------------------ */
/*  Per-run summary strip — every number labelled with its unit        */
/* ------------------------------------------------------------------ */

const RunStats: React.FC<{ run: TestRun }> = ({ run }) => {
  const stats = run.summary_stats;
  return (
    <div className="testing-summary-header">
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
        <span className="testing-summary-label">Duration</span>
        <span>{formatMs(stats?.duration_ms)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Started</span>
        <span>{formatTimestamp(run.started_at)}</span>
      </div>
      <div className="testing-summary-stat">
        <span className="testing-summary-label">Finished</span>
        <span>{formatTimestamp(run.finished_at)}</span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Per-assertion result row                                          */
/* ------------------------------------------------------------------ */

const AssertionResultRow: React.FC<{ result: AssertionResult }> = ({ result }) => {
  const [showPrompt, setShowPrompt] = useState(false);
  return (
    <div className="testing-assertion-result">
      {result.type === 'llm_judge' && (
        <div className="testing-judge-rubric">
          <div className="testing-judge-rubric-text">
            {result.rubric || '(prompt not recorded for this run)'}
          </div>
          {result.judge_prompt && (
            <>
              <button
                type="button"
                className="testing-raw-toggle"
                onClick={() => setShowPrompt((v) => !v)}
              >
                {showPrompt
                  ? 'Hide full prompt sent to the LLM'
                  : 'Show full prompt sent to the LLM'}
              </button>
              {showPrompt && (
                <pre className="testing-pre testing-pre-scroll">{result.judge_prompt}</pre>
              )}
            </>
          )}
        </div>
      )}
      <div className="testing-assertion-result-main">
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
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Human-friendly output: AI summary + sources, or search cards      */
/* ------------------------------------------------------------------ */

type OutputBlob = Record<string, unknown> | null | undefined;

const asArray = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? (v as Record<string, unknown>[]) : [];

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

const SourceCard: React.FC<{ r: Record<string, unknown>; index: number }> = ({
  r,
  index,
}) => {
  const title =
    str(r.title) || str(r.map_title) || str(r.doc_id) || `Result ${index + 1}`;
  const org = str(r.organization) || str(r.map_organization);
  const score = typeof r.score === 'number' ? r.score : undefined;
  const text = str(r.text);
  return (
    <div className="testing-result-card">
      <div className="testing-result-card-head">
        <span className="testing-result-card-num">{index + 1}</span>
        <span className="testing-result-card-title">{title}</span>
        {score !== undefined && (
          <span className="testing-result-card-score">{score.toFixed(3)}</span>
        )}
      </div>
      {org && <div className="testing-result-card-org">{org}</div>}
      {text && (
        <div className="testing-result-card-snippet">
          {text.length > 500 ? `${text.slice(0, 500)}…` : text}
        </div>
      )}
    </div>
  );
};

const ReferenceItem: React.FC<{ entry: Record<string, unknown> }> = ({ entry }) => {
  const title = str(entry.title) || str(entry.doc_id) || 'Unknown';
  const org = str(entry.organization);
  const year = entry.year !== null && entry.year !== undefined ? String(entry.year) : '';
  const url = str(entry.url);
  const meta = [org, year].filter(Boolean).join(', ');
  const num = entry.number !== undefined ? String(entry.number) : '';
  return (
    <li className="testing-reference">
      {num && <span className="testing-reference-num">[{num}]</span>}{' '}
      {url ? (
        <a href={url} target="_blank" rel="noreferrer">
          {title}
        </a>
      ) : (
        <span>{title}</span>
      )}
      {meta && <span className="text-muted"> — {meta}</span>}
    </li>
  );
};

const ResultOutput: React.FC<{ output: OutputBlob }> = ({ output }) => {
  const [showRaw, setShowRaw] = useState(false);
  if (!output) return <p className="text-muted" style={{ margin: 0 }}>No output.</p>;

  const summary = str(output.summary);
  const references = asArray(output.references);
  const sources = asArray(output.search_results);
  const searchResults = asArray(output.results);

  return (
    <div className="testing-output">
      {summary ? (
        <>
          <span className="testing-case-label">AI summary (with references)</span>
          <div className="testing-summary-text">{summary}</div>
          {references.length > 0 && (
            <>
              <span className="testing-case-label">
                Cited references ({references.length})
              </span>
              <ol className="testing-references">
                {references.map((entry, i) => (
                  <ReferenceItem key={i} entry={entry} />
                ))}
              </ol>
            </>
          )}
          {sources.length > 0 && (
            <>
              <span className="testing-case-label">Sources ({sources.length})</span>
              <div className="testing-result-cards">
                {sources.map((r, i) => (
                  <SourceCard key={i} r={r} index={i} />
                ))}
              </div>
            </>
          )}
        </>
      ) : searchResults.length > 0 ? (
        <>
          <span className="testing-case-label">Search results ({searchResults.length})</span>
          <div className="testing-result-cards">
            {searchResults.map((r, i) => (
              <SourceCard key={i} r={r} index={i} />
            ))}
          </div>
        </>
      ) : (
        <pre className="testing-pre testing-pre-scroll">{prettyJson(output)}</pre>
      )}

      <button
        type="button"
        className="testing-raw-toggle"
        onClick={() => setShowRaw((v) => !v)}
      >
        {showRaw ? 'Hide raw output' : 'Show raw output'}
      </button>
      {showRaw && (
        <pre className="testing-pre testing-pre-scroll">{prettyJson(output)}</pre>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Expandable result row                                             */
/* ------------------------------------------------------------------ */

const ResultRow: React.FC<{ result: TestResult; input?: Record<string, unknown> }> = ({
  result,
  input,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [showOutput, setShowOutput] = useState(false);
  return (
    <>
      <tr
        className="testing-clickable-row testing-result-row"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="testing-result-caret" aria-hidden>
          {expanded ? '▾' : '▸'}
        </td>
        <td className="testing-result-case" title={str(input?.query)}>
          {str(input?.query) || '—'}
        </td>
        <td>
          <span
            className={`testing-badge testing-badge-${result.status} testing-result-status`}
          >
            {result.status}
          </span>
        </td>
        <td>{formatScore(result.score)}</td>
        <td>{formatMs(result.latency_ms)}</td>
        <td className="testing-result-error">{result.error_message || ''}</td>
      </tr>
      {expanded && (
        <tr className="testing-result-detail-row">
          <td colSpan={6}>
            <div className="testing-result-detail">
              <div className="testing-case-block">
                <span className="testing-case-label">Query</span>
                <div className="testing-query">{str(input?.query) || '(no query)'}</div>
                {input && Object.keys(input).some((k) => k !== 'query') && (
                  <pre className="testing-pre">
                    {prettyJson(
                      Object.fromEntries(
                        Object.entries(input).filter(([k]) => k !== 'query'),
                      ),
                    )}
                  </pre>
                )}
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
                <button
                  type="button"
                  className="testing-collapse-toggle"
                  onClick={() => setShowOutput((v) => !v)}
                  aria-expanded={showOutput}
                >
                  <span className="testing-collapse-caret" aria-hidden>
                    {showOutput ? '▾' : '▸'}
                  </span>
                  <span className="testing-case-label">Output</span>
                </button>
                {showOutput && <ResultOutput output={result.actual_output} />}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/*  One run: collapsible header + its per-case results                */
/* ------------------------------------------------------------------ */

const passRateLevel = (rate?: number | null): string => {
  if (rate === null || rate === undefined) return 'none';
  if (rate >= 1) return 'good';
  if (rate > 0) return 'warn';
  return 'bad';
};

/* Live progress for an in-flight run: "k of N cases (z%)" plus a bar. The
   backend publishes `progress` on summary_stats while running and replaces it
   with the real stats on completion. */
const RunProgressBar: React.FC<{ progress?: RunProgress | null }> = ({ progress }) => {
  if (!progress) {
    return (
      <div className="testing-run-progress" role="status">
        <span className="testing-run-progress-label">Starting…</span>
      </div>
    );
  }
  const { completed, total } = progress;
  const fraction = total > 0 ? completed / total : 0;
  return (
    <div className="testing-run-progress" role="status">
      <div className="testing-run-progress-label">
        <span>
          {completed} of {total} {total === 1 ? 'case' : 'cases'} processed
        </span>
        <span className="testing-run-progress-pct">{formatPercent(fraction)}</span>
      </div>
      <div
        className="testing-run-progress-track"
        role="progressbar"
        aria-valuenow={completed}
        aria-valuemin={0}
        aria-valuemax={total}
      >
        <div
          className="testing-run-progress-fill"
          style={{ width: `${Math.round(fraction * 100)}%` }}
        />
      </div>
    </div>
  );
};

const RunSection: React.FC<{
  run: TestRun;
  caseInputs: Record<string, Record<string, unknown>>;
  defaultOpen: boolean;
  isLatest: boolean;
}> = ({ run, caseInputs, defaultOpen, isLatest }) => {
  const [open, setOpen] = useState(defaultOpen);
  const stats = run.summary_stats;
  const active = isActive(run.status);
  const results = run.results || [];
  const level = passRateLevel(stats?.pass_rate);
  return (
    <div className={`testing-run${isLatest ? ' testing-run--latest' : ''}`}>
      <button
        type="button"
        className={`testing-run-header${open ? ' testing-run-header--open' : ''}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="testing-run-caret" aria-hidden>{open ? '▾' : '▸'}</span>
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
              <span className="testing-run-metric-label">cases</span>
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
              <span className="testing-run-metric-label">score</span>
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
          {active && <RunProgressBar progress={stats?.progress} />}
          <RunStats run={run} />
          <table className="admin-table">
            <thead>
              <tr>
                <th aria-label="expand" />
                <th>Case</th>
                <th>Status</th>
                <th>Score</th>
                <th>Latency</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <ResultRow key={r.id} result={r} input={caseInputs[r.test_case_id]} />
              ))}
              {results.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-muted">
                    {active ? 'Running — results appear here as each case finishes…' : 'No results.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
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
