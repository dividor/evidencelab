import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { BriefCheckCandidate, BriefCitationCheck } from '../../../types/testing';
import { formatPercent, formatTimestamp } from './testingFormat';
import { VERDICT_LABEL } from './citationCheckFormat';

// The "Briefs" sub-view: pick one of your own or shared briefs and run the
// citation check on it. Lists the latest check per brief; opening a brief
// shows its check history.

interface BriefCheckListProps {
  // The model combo selected at the top of the page; null = the app default.
  modelCombo: string | null;
  onOpenCheck: (check: BriefCitationCheck) => void;
}

const POLL_INTERVAL_MS = 2000;
type Scope = 'all' | 'mine' | 'shared';

const isActive = (c?: BriefCitationCheck | null): boolean =>
  !!c && (c.status === 'pending' || c.status === 'running');

const lastCheckSummary = (check?: BriefCitationCheck | null): string => {
  if (!check) return 'Never checked';
  if (isActive(check)) return 'Running…';
  if (check.status === 'failed') return `Failed: ${check.summary_stats?.error || 'unknown error'}`;
  const stats = check.summary_stats || {};
  return `${stats.flagged ?? 0} of ${stats.total ?? 0} flagged (${formatPercent(
    stats.flagged_share,
  )})`;
};

const BriefCheckList: React.FC<BriefCheckListProps> = ({ modelCombo, onOpenCheck }) => {
  const [briefs, setBriefs] = useState<BriefCheckCandidate[]>([]);
  const [scope, setScope] = useState<Scope>('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchBriefs = useCallback(async () => {
    try {
      const resp = await axios.get<BriefCheckCandidate[]>(`${API_BASE_URL}/testing/briefs`);
      setBriefs(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load briefs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBriefs();
  }, [fetchBriefs]);

  // Poll while any brief's latest check is in flight.
  useEffect(() => {
    const anyActive = briefs.some((b) => isActive(b.last_check));
    if (anyActive && timerRef.current === null) {
      timerRef.current = setInterval(fetchBriefs, POLL_INTERVAL_MS);
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
  }, [briefs, fetchBriefs]);

  const handleRun = async (brief: BriefCheckCandidate) => {
    setBusyId(brief.id);
    setError('');
    try {
      const resp = await axios.post<BriefCitationCheck>(`${API_BASE_URL}/testing/brief-checks`, {
        brief_id: brief.id,
        model_combo: modelCombo || null,
      });
      onOpenCheck(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start the check');
    } finally {
      setBusyId(null);
    }
  };

  const needle = search.trim().toLowerCase();
  const visible = briefs.filter(
    (b) =>
      (scope === 'all' || (scope === 'shared') === b.shared) &&
      (!needle || b.title.toLowerCase().includes(needle)),
  );

  if (loading) return <div className="admin-loading">Loading...</div>;

  return (
    <div className="admin-section testing-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>
            &times;
          </button>
        </div>
      )}
      <p className="text-muted testing-brief-intro">
        Checks every cited passage of a brief against the exact source excerpts it cites. An LLM
        judge gives each passage a verdict and its supporting quotes are verified against the
        excerpts. Passages that are not fully supported are flagged for review.
      </p>
      <div className="testing-controls">
        <div className="testing-scope-toggle" role="group" aria-label="Brief scope">
          {(['all', 'mine', 'shared'] as Scope[]).map((s) => (
            <button
              key={s}
              className={`btn-sm ${scope === s ? 'btn-primary' : ''}`}
              aria-pressed={scope === s}
              onClick={() => setScope(s)}
            >
              {s === 'all' ? 'All' : s === 'mine' ? 'Mine' : 'Shared with me'}
            </button>
          ))}
        </div>
        <input
          className="testing-search-input"
          type="search"
          placeholder="Filter by title"
          aria-label="Filter briefs by title"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn-sm" onClick={fetchBriefs} style={{ marginLeft: 'auto' }}>
          Refresh
        </button>
      </div>

      {visible.length === 0 ? (
        <p className="text-muted">No briefs match.</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Brief</th>
              <th>Owner</th>
              <th>Data source</th>
              <th>Updated</th>
              <th>Sections</th>
              <th>Cited passages</th>
              <th>Last check</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((b) => {
              const last = b.last_check;
              return (
                <tr
                  key={b.id}
                  className={last ? 'testing-clickable-row' : ''}
                  onClick={() => last && onOpenCheck(last)}
                >
                  <td>
                    {b.title}
                    {b.shared && <span className="testing-config-badge">shared</span>}
                  </td>
                  <td>{b.owner_name}</td>
                  <td>{b.data_source || '—'}</td>
                  <td>{formatTimestamp(b.updated_at)}</td>
                  <td>{b.researched_sections}</td>
                  <td>{b.cited_passages}</td>
                  <td>
                    {last && (
                      <span className={`testing-status testing-status-${last.status}`}>
                        {last.status}
                      </span>
                    )}{' '}
                    <span className="text-muted">{lastCheckSummary(last)}</span>
                  </td>
                  <td onClick={(e) => e.stopPropagation()} className="testing-row-actions">
                    <button
                      className="btn-sm btn-primary"
                      onClick={() => handleRun(b)}
                      disabled={busyId === b.id || isActive(last) || b.cited_passages === 0}
                      title={
                        b.cited_passages === 0 ? 'This brief has no cited passages' : undefined
                      }
                    >
                      {busyId === b.id ? 'Starting...' : 'Run check'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="text-muted testing-brief-legend">
        Verdicts: {VERDICT_LABEL.supported} · {VERDICT_LABEL.partially_supported} ·{' '}
        {VERDICT_LABEL.unsupported} · {VERDICT_LABEL.cannot_assess}
      </p>
    </div>
  );
};

export default BriefCheckList;
