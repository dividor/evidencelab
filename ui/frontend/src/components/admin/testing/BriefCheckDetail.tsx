import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { SearchResult } from '../../../types/api';
import type {
  BriefCitationCheck,
  BriefCitationCheckDetail as CheckDetailType,
  BriefCitationCheckPassage,
  CheckQuote,
  CheckSource,
  CitationVerdict,
} from '../../../types/testing';
import { formatCostUsd, formatMs, formatPercent, formatTimestamp, formatTokens } from './testingFormat';
import {
  EMPTY_FILTERS,
  filterPassages,
  COLUMN_HELP,
  formatConfidence,
  PassageFilters,
  QUOTES_HELP,
  SUMMARY_HELP,
  VERDICT_HELP,
  VERDICT_LABEL,
  VERDICT_ORDER,
  VERDICT_TONE,
} from './citationCheckFormat';

// One citation check: summary, per-section crosstab, and the filterable
// passages table (the notebook's "All judgements" / "Flagged" sheets).

interface BriefCheckDetailProps {
  check: BriefCitationCheck;
  dataSource: string;
  onBack: () => void;
  // Opens a cited passage in the app's document preview (never a new window).
  onResultClick?: (result: SearchResult) => void;
}

type OpenSource = (source: CheckSource) => void;

// The SearchResult the app's document preview expects, from a stored source.
export const checkSourceToResult = (source: CheckSource, dataSource: string): SearchResult => ({
  chunk_id: source.chunk_id || '',
  doc_id: source.doc_id || '',
  title: source.title || 'Untitled',
  text: source.excerpt || '',
  page_num: source.page || 1,
  score: 0,
  headings: source.section ? source.section.split(' > ') : [],
  data_source: dataSource,
  report_url: source.pdf_url || undefined,
  metadata: {},
});

const POLL_INTERVAL_MS = 2000;

const COLUMNS: Array<{ key: string; label: string }> = [
  { key: 'passage_id', label: '#' },
  { key: 'section', label: 'Section' },
  { key: 'passage', label: 'Passage' },
  { key: 'cites', label: 'Cites' },
  { key: 'verdict', label: 'Verdict' },
  { key: 'confidence', label: 'Confidence' },
  { key: 'quotes_verified', label: 'Quotes verified' },
];

const isActive = (status?: string): boolean => status === 'pending' || status === 'running';

/* ------------------------------------------------------------------ */
/*  Summary header                                                    */
/* ------------------------------------------------------------------ */

const Summary: React.FC<{ detail: CheckDetailType }> = ({ detail }) => {
  const stats = detail.summary_stats || {};
  if (isActive(detail.status)) {
    const p = stats.progress;
    const fraction = p && p.total > 0 ? p.completed / p.total : 0;
    return (
      <div className="testing-run-progress" role="status">
        <div className="testing-run-progress-label">
          <span>{p ? `${p.completed} of ${p.total} passages judged` : 'Starting…'}</span>
          <span className="testing-run-progress-pct">{formatPercent(fraction)}</span>
        </div>
        <div className="testing-run-progress-track" role="progressbar" aria-valuenow={p?.completed ?? 0} aria-valuemin={0} aria-valuemax={p?.total ?? 0}>
          <div className="testing-run-progress-fill" style={{ width: `${Math.round(fraction * 100)}%` }} />
        </div>
      </div>
    );
  }
  if (detail.status === 'failed') {
    return <div className="auth-error">{stats.error || 'The check failed.'}</div>;
  }
  const verdicts = stats.verdicts || ({} as Record<CitationVerdict, number>);
  const tiles: Array<{ label: string; value: React.ReactNode; help: string }> = [
    { label: 'Passages', value: stats.total ?? 0, help: SUMMARY_HELP.passages },
    ...VERDICT_ORDER.map((v) => ({ label: VERDICT_LABEL[v], value: verdicts[v] ?? 0, help: VERDICT_HELP[v] })),
    {
      label: 'Flagged',
      value: `${stats.flagged ?? 0} (${formatPercent(stats.flagged_share)})`,
      help: SUMMARY_HELP.flagged,
    },
    { label: 'Quote not in source', value: stats.quote_not_in_source ?? 0, help: SUMMARY_HELP.quote_not_in_source },
    { label: 'Duration', value: formatMs(stats.duration_ms), help: SUMMARY_HELP.duration },
    { label: 'Tokens', value: formatTokens(stats.total_tokens), help: SUMMARY_HELP.tokens },
    { label: 'Cost', value: formatCostUsd(stats.cost_usd), help: SUMMARY_HELP.cost },
  ];
  return (
    <div className="testing-summary-header">
      {tiles.map((tile) => (
        <div key={tile.label} className="testing-summary-stat testing-has-help" title={tile.help}>
          <span className="testing-summary-label">{tile.label}</span> {tile.value}
        </div>
      ))}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Filters                                                           */
/* ------------------------------------------------------------------ */

const Filters: React.FC<{
  filters: PassageFilters;
  sections: string[];
  counts: Record<CitationVerdict, number>;
  onChange: (next: PassageFilters) => void;
}> = ({ filters, sections, counts, onChange }) => {
  const toggleVerdict = (v: CitationVerdict) => {
    const next = new Set(filters.verdicts);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    onChange({ ...filters, verdicts: next });
  };
  return (
    <div className="testing-controls testing-check-filters">
      <div className="testing-scope-toggle" role="group" aria-label="Verdict">
        {VERDICT_ORDER.map((v) => (
          <button
            key={v}
            className={`btn-sm ${filters.verdicts.has(v) ? 'btn-primary' : ''}`}
            aria-pressed={filters.verdicts.has(v)}
            onClick={() => toggleVerdict(v)}
          >
            {VERDICT_LABEL[v]} ({counts[v] ?? 0})
          </button>
        ))}
      </div>
      <label className="testing-inline-check">
        <input
          type="checkbox"
          checked={filters.flaggedOnly}
          onChange={(e) => onChange({ ...filters, flaggedOnly: e.target.checked })}
        />
        Flagged only
      </label>
      <label className="testing-inline-check">
        <input
          type="checkbox"
          checked={filters.quoteNotInSource}
          onChange={(e) => onChange({ ...filters, quoteNotInSource: e.target.checked })}
        />
        Quote not in source
      </label>
      <select
        className="testing-filter-select"
        aria-label="Section"
        value={filters.section}
        onChange={(e) => onChange({ ...filters, section: e.target.value })}
      >
        <option value="">All sections</option>
        {sections.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <input
        className="testing-search-input"
        type="search"
        placeholder="Search passages"
        aria-label="Search passages"
        value={filters.search}
        onChange={(e) => onChange({ ...filters, search: e.target.value })}
      />
      <button className="btn-sm" onClick={() => onChange(EMPTY_FILTERS)}>
        Clear
      </button>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Passage row + detail                                              */
/* ------------------------------------------------------------------ */

const QuoteLine: React.FC<{ quote: CheckQuote }> = ({ quote }) => (
  <li>
    <span className={`testing-status testing-status-${quote.status === 'missing' ? 'failed' : quote.status === 'near' ? 'pending' : 'completed'}`}>
      {quote.status}
    </span>{' '}
    [{quote.citation ?? '?'}] “{quote.quote}”
  </li>
);

const sourceLabel = (source: CheckSource): string => {
  const pageSuffix = source.page ? `, p. ${source.page}` : '';
  return `[${source.index}] ${source.title || 'Untitled'}${pageSuffix}`;
};

const SourceBlock: React.FC<{ source: CheckSource; onOpen?: OpenSource }> = ({ source, onOpen }) => (
  <div className="testing-case-block">
    <div className="testing-case-label">
      {onOpen ? (
        <button type="button" className="testing-link-btn" onClick={() => onOpen(source)}>
          {sourceLabel(source)}
        </button>
      ) : (
        sourceLabel(source)
      )}
      {source.section && <span className="text-muted"> — {source.section}</span>}
    </div>
    <pre className="testing-pre testing-pre-scroll">{source.excerpt}</pre>
  </div>
);

const PassageDetail: React.FC<{ passage: BriefCitationCheckPassage; onOpen?: OpenSource }> = ({
  passage,
  onOpen,
}) => (
  <div className="testing-check-passage-detail">
    {passage.error_message && <div className="auth-error">{passage.error_message}</div>}
    {passage.problems.length > 0 && (
      <div className="testing-case-block">
        <div className="testing-case-label">Problems</div>
        <ul className="testing-check-list">
          {passage.problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      </div>
    )}
    <div className="testing-case-block">
      <div className="testing-case-label">Explanation</div>
      <p>{passage.explanation}</p>
    </div>
    {passage.supporting_quotes.length > 0 && (
      <div className="testing-case-block">
        <div className="testing-case-label">
          Supporting quotes ({passage.quotes_verified} verified){' '}
          <span className="testing-help-icon" title={QUOTES_HELP} aria-label={QUOTES_HELP} role="img">
            ⓘ
          </span>
        </div>
        <ul className="testing-check-list">
          {passage.supporting_quotes.map((q, i) => (
            <QuoteLine key={i} quote={q} />
          ))}
        </ul>
      </div>
    )}
    {passage.sources.map((s) => (
      <SourceBlock key={`${s.index}-${s.chunk_id}`} source={s} onOpen={onOpen} />
    ))}
  </div>
);

const CitationLinks: React.FC<{ passage: BriefCitationCheckPassage; onOpen?: OpenSource }> = ({
  passage,
  onOpen,
}) => (
  <span className="testing-citation-links" onClick={(e) => e.stopPropagation()}>
    {passage.sources.map((s) => (
      <button
        key={`${s.index}-${s.chunk_id}`}
        type="button"
        className="testing-link-btn"
        title={`Open ${sourceLabel(s)} in Evidence Lab`}
        disabled={!onOpen}
        onClick={() => onOpen && onOpen(s)}
      >
        [{s.index}]
      </button>
    ))}
    {passage.dangling_citations && (
      <span className="text-muted" title="No source is stored for these citation numbers">
        [{passage.dangling_citations}]
      </span>
    )}
  </span>
);

const PassageRow: React.FC<{ passage: BriefCitationCheckPassage; onOpen?: OpenSource }> = ({
  passage,
  onOpen,
}) => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className={`testing-clickable-row${open ? ' testing-row-expanded' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={open ? 'Hide details' : 'Show the judge\'s reasoning and the cited excerpts'}
      >
        <td className="testing-result-caret" aria-hidden>
          {open ? '▾' : '▸'}
        </td>
        <td>{passage.passage_id}</td>
        <td>{passage.brief_section}</td>
        <td className="testing-check-passage">{passage.passage}</td>
        <td>
          <CitationLinks passage={passage} onOpen={onOpen} />
        </td>
        <td>
          <span
            className={`testing-status testing-status-${VERDICT_TONE[passage.verdict]}`}
            title={VERDICT_HELP[passage.verdict]}
          >
            {VERDICT_LABEL[passage.verdict]}
          </span>
        </td>
        <td>{formatConfidence(passage.confidence)}</td>
        <td>
          {passage.quotes_verified}
          {passage.quote_not_in_source && (
            <span className="testing-config-badge testing-badge-warn">quote not in source</span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="testing-check-detail-row">
          <td colSpan={COLUMNS.length + 1}>
            <PassageDetail passage={passage} onOpen={onOpen} />
          </td>
        </tr>
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/*  Detail view                                                       */
/* ------------------------------------------------------------------ */

const BriefCheckDetail: React.FC<BriefCheckDetailProps> = ({
  check,
  dataSource,
  onBack,
  onResultClick,
}) => {
  const openSource: OpenSource | undefined = onResultClick
    ? (source) => onResultClick(checkSourceToResult(source, dataSource))
    : undefined;
  const [detail, setDetail] = useState<CheckDetailType | null>(null);
  const [filters, setFilters] = useState<PassageFilters>(EMPTY_FILTERS);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDetail = useCallback(async () => {
    try {
      const resp = await axios.get<CheckDetailType>(`${API_BASE_URL}/testing/brief-checks/${check.id}`);
      setDetail(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load the check');
    }
  }, [check.id]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

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

  const passages = useMemo(() => detail?.passages || [], [detail]);
  const sections = useMemo(
    () => Array.from(new Set(passages.map((p) => p.brief_section))),
    [passages],
  );
  const counts = useMemo(() => {
    const out = { supported: 0, partially_supported: 0, unsupported: 0, cannot_assess: 0 };
    passages.forEach((p) => {
      out[p.verdict] += 1;
    });
    return out;
  }, [passages]);
  const visible = useMemo(() => filterPassages(passages, filters), [passages, filters]);

  const handleCancel = async () => {
    setBusy(true);
    try {
      await axios.post(`${API_BASE_URL}/testing/brief-checks/${check.id}/cancel`);
      await fetchDetail();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to cancel the check');
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    setBusy(true);
    try {
      const resp = await axios.get(`${API_BASE_URL}/testing/brief-checks/${check.id}/export.xlsx`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(resp.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `citation_check_${check.brief_id}.xlsx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to export the check');
    } finally {
      setBusy(false);
    }
  };

  const status = detail?.status || check.status;
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
      <div className="testing-controls">
        <button className="btn-sm" onClick={onBack}>
          &larr; Briefs
        </button>
        <div>
          <strong>{check.brief_title}</strong>
          <div className="text-muted">
            Checked {formatTimestamp(check.created_at)} · judge {check.judge_model || '—'}
            {check.model_combo ? ` (${check.model_combo})` : ''}
          </div>
        </div>
        <span className={`testing-status testing-status-${status}`}>{status}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
          {isActive(status) && (
            <button className="btn-sm btn-danger" onClick={handleCancel} disabled={busy}>
              Cancel
            </button>
          )}
          <button
            className="btn-sm"
            onClick={handleExport}
            disabled={busy || status !== 'completed'}
          >
            Download Excel
          </button>
        </div>
      </div>

      {detail && <Summary detail={detail} />}

      {passages.length > 0 && (
        <>
          <Filters filters={filters} sections={sections} counts={counts} onChange={setFilters} />
          <p className="text-muted">
            Showing {visible.length} of {passages.length} passages. Click a row for the judge's
            reasoning and the cited excerpts. Hover a column heading or a verdict for what it
            means.
          </p>
          <table className="admin-table testing-check-table">
            <thead>
              <tr>
                <th aria-label="expand" />
                {COLUMNS.map((c) => (
                  <th key={c.key} className="testing-has-help" title={COLUMN_HELP[c.key]}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <PassageRow key={p.id} passage={p} onOpen={openSource} />
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
};

export default BriefCheckDetail;
