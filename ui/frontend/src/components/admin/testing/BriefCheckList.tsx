import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { BriefAccess, BriefCheckCandidate, BriefCitationCheck } from '../../../types/testing';
import { ClaimHeaders, ClaimCells } from './BriefScoreStats';
import { formatPercent, formatElapsed, formatScore, formatTimestamp } from './testingFormat';
import { VERDICT_LABEL } from './citationCheckFormat';

// The "Briefs" sub-view: pick a brief and run the citation check on it. Admins
// see every user's brief, not only their own and the ones shared with them.
// Lists the latest check per brief; opening a brief shows its check history.

interface BriefCheckListProps {
  // The model combo selected at the top of the page; null = the app default.
  modelCombo: string | null;
  onOpenCheck: (check: BriefCitationCheck) => void;
}

const POLL_INTERVAL_MS = 2000;
type Scope = 'all' | BriefAccess;
const SCOPES: { value: Scope; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'own', label: 'Mine' },
  { value: 'shared', label: 'Shared with me' },
  { value: 'other', label: 'Other users' },
];

const isActive = (c?: BriefCitationCheck | null): boolean =>
  !!c && (c.status === 'pending' || c.status === 'running');

const lastCheckSummary = (check?: BriefCitationCheck | null): string => {
  if (!check) return 'Never checked';
  if (isActive(check)) return 'Running…';
  if (check.status === 'failed') return `Failed: ${check.summary_stats?.error || 'unknown error'}`;
  const stats = check.summary_stats || {};
  if (stats.section_counts) {
    const counts = stats.section_counts;
    return `Full Brief check · ${counts.pass} sections passed, ${counts.fail} failed, ${counts.error} with errors`;
  }
  return `Citation check · ${stats.flagged ?? 0} of ${stats.total ?? 0} flagged (${formatPercent(
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
      (scope === 'all' || scope === b.access) &&
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
        Run the nine standard Brief experiment checks on the saved version. Open a result to review
        each section’s writing, relevance, length, overlap and factual support, including uncited claims.
      </p>
      <div className="testing-controls">
        <div className="testing-scope-toggle" role="group" aria-label="Brief scope">
          {SCOPES.map((s) => (
            <button
              key={s.value}
              className={`btn-sm ${scope === s.value ? 'btn-primary' : ''}`}
              aria-pressed={scope === s.value}
              onClick={() => setScope(s.value)}
            >
              {s.label}
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
        <div className="admin-table-scroll" role="region" aria-label="Saved briefs table" tabIndex={0}>
          <table className="admin-table testing-saved-briefs-table" aria-label="Saved briefs">
            <thead>
              <tr>
                <th>Brief and data source</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Sections</th>
                <th>Cited passages</th>
                <th>Pass rate</th><th>Mean Total Score</th><ClaimHeaders /><th>Duration</th>
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
                    <td className="testing-brief-section-title" title={b.title}>
                      <strong>{b.title}</strong>
                      <small>{b.data_source}</small>
                      {b.access === 'shared' && <span className="testing-config-badge">shared</span>}
                    </td>
                    <td>{b.owner_name}</td>
                    <td>{last ? <span className={`testing-status testing-status-${last.status}`}>{last.status}</span> : '—'}</td>
                    <td>{formatTimestamp(b.updated_at)}</td>
                    <td>{b.researched_sections}</td>
                    <td>{b.cited_passages}</td>
                    <td>{formatPercent(last?.summary_stats?.pass_rate)}</td>
                    <td>{formatScore(last?.summary_stats?.mean_score)}</td>
                    <ClaimCells stats={last?.summary_stats} />
                    <td>{formatElapsed(last?.summary_stats?.duration_ms)}</td>
                    <td>
                      <span className="text-muted">{lastCheckSummary(last)}</span>
                      {last?.brief_version_number != null && (
                        <span
                          className="text-muted testing-check-version"
                          title="The brief version this check judged"
                        >
                          {' '}
                          v{last.brief_version_number}
                        </span>
                      )}
                      {last?.brief_changed && (
                        <span
                          className="testing-config-badge"
                          title="The brief has a newer version than the one this check judged"
                        >
                          brief changed since
                        </span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn-sm btn-primary"
                        onClick={() => handleRun(b)}
                        disabled={busyId === b.id || isActive(last) || b.researched_sections === 0}
                        title={
                          b.researched_sections === 0 ? 'This brief has no written sections' : undefined
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
        </div>
      )}
      <p className="text-muted testing-brief-legend">
        Verdicts: {VERDICT_LABEL.supported} · {VERDICT_LABEL.partially_supported} ·{' '}
        {VERDICT_LABEL.unsupported} · {VERDICT_LABEL.cannot_assess}
      </p>
    </div>
  );
};

export default BriefCheckList;
