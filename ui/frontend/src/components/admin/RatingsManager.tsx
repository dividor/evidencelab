import React, { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { SortableHeader } from '../documents/SortableHeader';

interface RatingRow {
  id: string;
  user_id: string;
  user_email: string | null;
  user_display_name: string | null;
  rating_type: string;
  reference_id: string;
  item_id: string | null;
  score: number;
  comment: string | null;
  context: Record<string, any> | null;
  url: string | null;
  created_at: string;
  updated_at: string;
}

interface RatingsResponse {
  items: RatingRow[];
  total: number;
  page: number;
  page_size: number;
}

const RATING_TYPES = ['search_result', 'ai_summary', 'doc_summary', 'taxonomy'];
const SCORE_OPTIONS = ['1', '2', '3', '4', '5'];

// Static filter options — user_email is dynamic (computed from data)
const STATIC_FILTER_OPTIONS: Record<string, string[]> = {
  rating_type: RATING_TYPES,
  score: SCORE_OPTIONS,
};

const formatDate = (iso: string) => {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

const renderStars = (score: number) => {
  return '\u2605'.repeat(score) + '\u2606'.repeat(5 - score);
};

// ---------------------------------------------------------------------------
// Chevron SVG icon for expand/collapse
// ---------------------------------------------------------------------------
const ChevronIcon: React.FC<{ expanded: boolean }> = ({ expanded }) => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 20 20"
    fill="none"
    style={{
      transition: 'transform 0.2s ease',
      transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
    }}
  >
    <path
      d="M7 5l5 5-5 5"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------
const isUrl = (val: string): boolean =>
  /^https?:\/\//i.test(val) || /^www\./i.test(val);

/** Render a value as a clickable link if it looks like a URL */
const AutoLink: React.FC<{ value: string; style?: React.CSSProperties }> = ({ value, style }) => {
  if (isUrl(value)) {
    const href = value.startsWith('www.') ? `https://${value}` : value;
    return (
      <a href={href} target="_blank" rel="noopener noreferrer"
        style={{ color: '#1a73e8', wordBreak: 'break-all', ...style }}
        onClick={(e) => e.stopPropagation()}>{value}</a>
    );
  }
  return <span style={style}>{value}</span>;
};

// Fields that belong in the search result cards, NOT in the header fields area
const RESULT_CARD_FIELDS = new Set([
  'title', 'doc_id', 'chunk_id', 'page_num', 'chunk_text', 'score',
  'relevance_score', 'link', 'ai_summary', 'results_snapshot', 'summary',
]);

/**
 * Build a citation renderer that creates clickable citation badges.
 * Each badge shows the document title on hover and links to the source.
 */
const CITE_SPLIT = /(\[\d+(?:\s*,\s*\d+)*\](?!\())/g;
const CITE_MATCH = /^\[(\d+(?:\s*,\s*\d+)*)\]$/;
const CITE_EXTRACT = /\[(\d+(?:,\s*\d+)*)\]/g;

const buildCitationBadge = (num: number, results: any[], i: number, j: number) => {
  const idx = num - 1;
  const r = idx >= 0 && idx < results.length ? results[idx] : null;
  if (r?.link) {
    const pageSuffix = r.page_num ? ', p.' + String(r.page_num) : '';
    const tip = (r.title || 'Untitled') + pageSuffix;
    return (
      <a key={`c${i}-${j}`} href={r.link} target="_blank" rel="noopener noreferrer"
        className="admin-citation-badge admin-citation-clickable" title={tip}
        onClick={(e) => e.stopPropagation()}>{num}</a>
    );
  }
  return <span key={`c${i}-${j}`} className="admin-citation-badge">{num}</span>;
};

const createCitationRenderer = (results: any[]) => {
  const render = (children: React.ReactNode): React.ReactNode => {
    return React.Children.map(children, (child) => {
      if (typeof child === 'string') {
        const parts = child.split(CITE_SPLIT);
        if (parts.length === 1) return child;
        return parts.map((part, i) => {
          const m = part.match(CITE_MATCH);
          if (m) {
            return m[1].split(',').map((n, j) =>
              buildCitationBadge(parseInt(n.trim(), 10), results, i, j),
            );
          }
          return part || null;
        });
      }
      if (React.isValidElement(child) && (child.props as any).children) {
        return React.cloneElement(
          child as React.ReactElement<any>,
          {},
          render((child.props as any).children),
        );
      }
      return child;
    });
  };
  return render;
};

/** Extract all cited numbers, map to results, group by document title */
const buildGroupedRefs = (summary: string, results: any[]) => {
  const cited = new Set<number>();
  let m: RegExpExecArray | null;
  const re = new RegExp(CITE_EXTRACT.source, 'g');
  while ((m = re.exec(summary)) !== null) {
    m[1].split(',').forEach((n) => cited.add(parseInt(n.trim(), 10)));
  }
  if (cited.size === 0 || !results?.length) return [];
  const groups = new Map<string, { title: string; org?: string; year?: string; refs: { num: number; result: any }[] }>();
  const order: string[] = [];
  const sorted = Array.from(cited).sort((a, b) => a - b);
  sorted.forEach((origNum, seqIdx) => {
    const idx = origNum - 1;
    if (idx < 0 || idx >= results.length) return;
    const r = results[idx];
    const key = r.title || `result-${idx}`;
    if (!groups.has(key)) {
      groups.set(key, { title: r.title || 'Untitled', org: r.organization, year: r.year, refs: [] });
      order.push(key);
    }
    groups.get(key)!.refs.push({ num: seqIdx + 1, result: r });
  });
  return order.map((k) => groups.get(k)!);
};

/** References section matching the main search view style */
const AdminReferences: React.FC<{ summary: string; results: any[] }> = ({ summary, results }) => {
  const groups = buildGroupedRefs(summary, results);
  if (groups.length === 0) return null;
  return (
    <div className="admin-references-section">
      <h4>References:</h4>
      {groups.map((g) => (
        <div key={g.title} className="admin-ref-group">
          <span>{g.title}{g.org && `, ${g.org}`}{g.year && `, ${g.year}`}</span>
          {' | '}
          {g.refs.map(({ num, result }, i) => (
            <React.Fragment key={num}>
              {i > 0 && ' '}
              {result.link ? (
                <a href={result.link} target="_blank" rel="noopener noreferrer"
                  className="admin-ref-link" onClick={(e) => e.stopPropagation()}>
                  <span className="admin-citation-badge admin-citation-clickable">{num}</span>
                  {result.page_num ? ` p.${result.page_num}` : ''}
                </a>
              ) : (
                <span className="admin-citation-badge">{num}</span>
              )}
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Context detail components
// ---------------------------------------------------------------------------

/** Collapsible results snapshot — full result cards with clickable titles */
const ResultsSnapshotList: React.FC<{ results: any[] }> = ({ results }) => {
  const [expanded, setExpanded] = useState(false);
  if (!results || results.length === 0) return null;
  const visible = expanded ? results : results.slice(0, 3);

  return (
    <div style={{ marginTop: 12 }}>
      <div className="admin-context-label">
        Search Results ({results.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {visible.map((r: any, i: number) => (
          <div key={i} className="admin-result-card">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {r.link || r.url ? (
                <a href={r.link || r.url} target="_blank" rel="noopener noreferrer"
                  className="admin-result-title-link"
                  onClick={(e) => e.stopPropagation()}>
                  {r.title || 'Untitled'}
                </a>
              ) : (
                <span style={{ color: '#1a1f36' }}>{r.title || 'Untitled'}</span>
              )}
            </div>
            <div className="admin-result-meta">
              {r.doc_id && <span>Doc: {r.doc_id}</span>}
              {r.chunk_id && <><span className="admin-meta-sep">|</span><span>Chunk: {r.chunk_id}</span></>}
              {r.page_num && <><span className="admin-meta-sep">|</span><span>Page {r.page_num}</span></>}
              {r.score != null && (
                <><span className="admin-meta-sep">|</span>
                <span>Score: {typeof r.score === 'number' ? r.score.toFixed(3) : r.score}</span></>
              )}
            </div>
            {r.chunk_text && (
              <div className="admin-result-chunk-text">
                {r.chunk_text}
              </div>
            )}
          </div>
        ))}
      </div>
      {results.length > 3 && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded((prev) => !prev); }}
          className="admin-show-more-btn"
        >
          {expanded ? 'Show less' : `Show ${results.length - 3} more...`}
        </button>
      )}
    </div>
  );
};

/** Render AI summary as markdown with clickable citation badges and references */
const AiSummaryBlock: React.FC<{ summary: string; results?: any[] }> = ({ summary, results = [] }) => {
  if (!summary) return null;
  const renderCitations = createCitationRenderer(results);

  return (
    <div style={{ marginTop: 12 }}>
      <div className="admin-context-label">AI Summary</div>
      <div className="admin-summary-block">
        <ReactMarkdown
          components={{
            a: ({ node, ...props }) => (
              <a {...props} target="_blank" rel="noopener noreferrer"
                style={{ color: '#1a73e8' }} onClick={(e) => e.stopPropagation()} />
            ),
            p: ({ node, children, ...props }) => (
              <p style={{ marginBottom: '0.6rem', lineHeight: '1.6' }} {...props}>
                {renderCitations(children)}
              </p>
            ),
            li: ({ node, children, ...props }) => (
              <li style={{ marginBottom: '0.3rem' }} {...props}>
                {renderCitations(children)}
              </li>
            ),
            ul: ({ node, ...props }) => <ul style={{ paddingLeft: '1.2rem', marginBottom: '0.6rem' }} {...props} />,
            ol: ({ node, ...props }) => <ol style={{ paddingLeft: '1.2rem', marginBottom: '0.6rem' }} {...props} />,
            h1: ({ node, ...props }) => <h4 style={{ marginTop: '0.8rem', marginBottom: '0.4rem' }} {...props} />,
            h2: ({ node, ...props }) => <h4 style={{ marginTop: '0.8rem', marginBottom: '0.4rem' }} {...props} />,
            h3: ({ node, ...props }) => <h5 style={{ marginTop: '0.6rem', marginBottom: '0.3rem' }} {...props} />,
          }}
        >
          {summary}
        </ReactMarkdown>
        {results.length > 0 && <AdminReferences summary={summary} results={results} />}
      </div>
    </div>
  );
};

/** Display high-level context fields only (not chunk-level fields) */
const ContextFields: React.FC<{ context: Record<string, any>; exclude?: string[] }> = ({
  context,
  exclude = [],
}) => {
  const skip = new Set([...exclude, ...RESULT_CARD_FIELDS]);
  const entries = Object.entries(context).filter(
    ([key]) => !skip.has(key) && context[key] != null && context[key] !== ''
  );
  if (entries.length === 0) return null;

  return (
    <div className="admin-context-fields">
      {entries.map(([key, val]) => (
        <React.Fragment key={key}>
          <span className="admin-context-key">{key.replace(/_/g, ' ')}:</span>
          <span className="admin-context-value">
            {typeof val === 'string' && isUrl(val) ? (
              <AutoLink value={val} />
            ) : typeof val === 'object' ? (
              JSON.stringify(val)
            ) : (
              String(val)
            )}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
};

/** Full context panel for a rating row */
const RatingContextPanel: React.FC<{ rating: RatingRow }> = ({ rating }) => {
  const ctx = rating.context;
  if (!ctx || Object.keys(ctx).length === 0) {
    return <span className="admin-no-data">No context data</span>;
  }

  const aiSummary = ctx.ai_summary || ctx.summary || '';
  const resultsSnapshot = ctx.results_snapshot;

  return (
    <div>
      <ContextFields context={ctx} />
      {aiSummary && (
        <AiSummaryBlock summary={aiSummary}
          results={Array.isArray(resultsSnapshot) ? resultsSnapshot : []} />
      )}
      {resultsSnapshot && Array.isArray(resultsSnapshot) && (
        <ResultsSnapshotList results={resultsSnapshot} />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Filter popover for categorical columns
// ---------------------------------------------------------------------------
interface FilterPopoverProps {
  column: string;
  position: { top: number; left: number };
  currentValue: string;
  options: string[];
  onApply: (column: string, value: string) => void;
  onClear: (column: string) => void;
  onClose: () => void;
}

const FilterPopover: React.FC<FilterPopoverProps> = ({
  column,
  position,
  currentValue,
  options,
  onApply,
  onClear,
  onClose,
}) => {
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={popoverRef}
      className="filter-popover"
      style={{ position: 'fixed', top: position.top, left: position.left, zIndex: 1100 }}
    >
      <div className="filter-popover-header">
        <span>Filter {column.replace(/_/g, ' ')}</span>
        <button className="filter-popover-close" onClick={onClose} aria-label="Close filter">×</button>
      </div>
      <div className="filter-popover-content">
        <div className="filter-list">
          <div
            className={`filter-list-item ${!currentValue ? 'selected' : ''}`}
            onClick={() => { onClear(column); onClose(); }}
          >
            <span>All</span>
          </div>
          {options.map((opt) => (
            <div
              key={opt}
              className={`filter-list-item ${currentValue === opt ? 'selected' : ''}`}
              onClick={() => { onApply(column, opt); onClose(); }}
            >
              <span>{opt.replace(/_/g, ' ')}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Client-side filter helpers (extracted to reduce cognitive complexity)
// ---------------------------------------------------------------------------
const matchesScoreFilter = (row: RatingRow, filterVal: string): boolean =>
  !filterVal || String(row.score) === filterVal;

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const RatingsManager: React.FC = () => {
  const [ratings, setRatings] = useState<RatingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [filterType, setFilterType] = useState('all');
  const [exporting, setExporting] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [activeFilterColumn, setActiveFilterColumn] = useState<string | null>(null);
  const [filterPopoverPosition, setFilterPopoverPosition] = useState({ top: 0, left: 0 });

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const toggleRow = (id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const fetchRatings = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: Record<string, any> = { page, page_size: pageSize, sort_by: sortBy, order };
      if (search) params.search = search;
      if (filterType !== 'all') params.rating_type = filterType;
      const uf = columnFilters['user_email'];
      if (uf) params.user_email = uf;
      const resp = await axios.get<RatingsResponse>(`${API_BASE_URL}/ratings/all`, { params });
      setRatings(resp.data.items);
      setTotal(resp.data.total);
    } catch {
      setError('Failed to load ratings');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, sortBy, order, filterType, columnFilters]);

  useEffect(() => { fetchRatings(); }, [fetchRatings]);
  useEffect(() => { setExpandedRows(new Set()); }, [page, filterType, search, sortBy, order]);

  const handleSort = (col: string) => {
    if (sortBy === col) setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(col); setOrder('desc'); }
    setPage(1);
  };

  const handleSearchSubmit = (e: React.FormEvent) => { e.preventDefault(); setSearch(searchInput); setPage(1); };

  const handleSearchInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchInput(e.target.value);
    if (!e.target.value) { setSearch(''); setPage(1); }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const params: Record<string, string> = {};
      if (filterType !== 'all') params.rating_type = filterType;
      const resp = await axios.get<Blob>(`${API_BASE_URL}/ratings/export`, { params, responseType: 'blob' });
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement('a');
      a.href = url; a.download = 'ratings_export.xlsx';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch { setError('Export failed'); }
    finally { setExporting(false); }
  };

  const handleFilterClick = useCallback((column: string, event: React.MouseEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setFilterPopoverPosition({ top: rect.bottom + 4, left: Math.max(8, rect.left - 60) });
    setActiveFilterColumn((prev) => (prev === column ? null : column));
  }, []);

  const hasActiveFilter = useCallback(
    (column: string) => {
      if (column === 'rating_type') return filterType !== 'all';
      return !!columnFilters[column];
    },
    [filterType, columnFilters],
  );

  // Server-side filter columns trigger a page reset + re-fetch
  const SERVER_FILTER_COLUMNS = new Set(['rating_type', 'user_email']);

  const handleApplyFilter = useCallback((column: string, value: string) => {
    if (column === 'rating_type') {
      setFilterType(value);
    }
    setColumnFilters((prev) => ({ ...prev, [column]: value }));
    if (SERVER_FILTER_COLUMNS.has(column)) setPage(1);
  }, []);

  const handleClearFilter = useCallback((column: string) => {
    if (column === 'rating_type') {
      setFilterType('all');
    }
    setColumnFilters((prev) => {
      const next = { ...prev };
      delete next[column];
      return next;
    });
    if (SERVER_FILTER_COLUMNS.has(column)) setPage(1);
  }, []);

  const hasContext = (r: RatingRow) => r.context && Object.keys(r.context).length > 0;

  // Apply client-side column filters (score)
  const filteredRatings = ratings.filter((r) =>
    matchesScoreFilter(r, columnFilters['score'] || ''),
  );

  // Dynamic user email options from current data
  const uniqueUsers = React.useMemo(() => {
    const emails = new Set<string>();
    ratings.forEach((r) => { if (r.user_email) emails.add(r.user_email); });
    return Array.from(emails).sort();
  }, [ratings]);

  const getFilterOptions = (column: string): string[] => {
    if (column === 'user_email') return uniqueUsers;
    return STATIC_FILTER_OPTIONS[column] || [];
  };

  const getFilterValue = (column: string): string => {
    if (column === 'rating_type') return filterType === 'all' ? '' : filterType;
    return columnFilters[column] || '';
  };

  return (
    <div className="admin-section" style={{ position: 'relative' }}>
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="admin-controls" style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input type="text" placeholder="Search by email, reference, or comment..." value={searchInput}
            onChange={handleSearchInputChange} className="admin-search-input"
            style={{ minWidth: '250px', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid #ccc', fontSize: '0.85rem' }} />
          <button type="submit" className="btn-sm" style={{ padding: '0.4rem 0.8rem' }}>Search</button>
        </form>
        <button className="admin-download-button" onClick={handleExport} disabled={exporting} style={{ marginLeft: 'auto' }}>
          <span className="admin-download-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20" focusable="false">
              <path d="M10 2a1 1 0 0 1 1 1v7.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42l2.3 2.3V3a1 1 0 0 1 1-1zm-6 12a1 1 0 0 1 1 1v2h10v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z" fill="currentColor" />
            </svg>
          </span>
          {exporting ? 'Downloading...' : 'Download Ratings'}
        </button>
      </div>

      <p className="text-muted" style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>
        {total} rating{total !== 1 ? 's' : ''} found
      </p>

      {loading ? (
        <div className="admin-loading">Loading ratings...</div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}></th>
                  <SortableHeader columnKey="created_at" label="Date" sortField={sortBy} sortDirection={order}
                    onSort={handleSort} onFilterClick={handleFilterClick} hasActiveFilter={hasActiveFilter} />
                  <SortableHeader columnKey="user_email" label="User" filterable sortField={sortBy} sortDirection={order}
                    onSort={handleSort} onFilterClick={handleFilterClick} hasActiveFilter={hasActiveFilter} />
                  <SortableHeader columnKey="rating_type" label="Type" filterable sortField={sortBy} sortDirection={order}
                    onSort={handleSort} onFilterClick={handleFilterClick} hasActiveFilter={hasActiveFilter} />
                  <SortableHeader columnKey="score" label="Score" filterable sortField={sortBy} sortDirection={order}
                    onSort={handleSort} onFilterClick={handleFilterClick} hasActiveFilter={hasActiveFilter} />
                  <th>Comment</th>
                  <th>URL</th>
                </tr>
              </thead>
              <tbody>
                {filteredRatings.length === 0 ? (
                  <tr><td colSpan={7} style={{ textAlign: 'center', padding: '1.5rem', color: '#888' }}>No ratings found</td></tr>
                ) : (
                  filteredRatings.map((r) => {
                    const isExpanded = expandedRows.has(r.id);
                    return (
                      <React.Fragment key={r.id}>
                        <tr className={`${hasContext(r) ? 'admin-expandable-row' : ''} ${isExpanded ? 'admin-expanded-parent' : ''}`}
                          onClick={() => hasContext(r) && toggleRow(r.id)}>
                          <td style={{ textAlign: 'center', padding: '0.4rem' }}>
                            {hasContext(r) ? (
                              <span className="admin-expand-icon">
                                <ChevronIcon expanded={isExpanded} />
                              </span>
                            ) : ''}
                          </td>
                          <td style={{ whiteSpace: 'nowrap', fontSize: '0.82rem' }}>{formatDate(r.created_at)}</td>
                          <td style={{ fontSize: '0.82rem' }}>{r.user_email || r.user_display_name || '-'}</td>
                          <td style={{ fontSize: '0.82rem' }}>{r.rating_type.replace(/_/g, ' ')}</td>
                          <td style={{ color: '#d4a017', fontSize: '0.9rem', letterSpacing: '1px' }}>{renderStars(r.score)}</td>
                          <td style={{ fontSize: '0.82rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.comment || ''}>{r.comment || '-'}</td>
                          <td style={{ fontSize: '0.82rem', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.url || ''}>
                            {r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" style={{ color: '#1a73e8' }} onClick={(e) => e.stopPropagation()}>link</a> : '-'}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="admin-expanded-detail">
                            <td colSpan={7} className="admin-expanded-cell">
                              <RatingContextPanel rating={r} />
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {activeFilterColumn && (
            <FilterPopover
              column={activeFilterColumn}
              position={filterPopoverPosition}
              currentValue={getFilterValue(activeFilterColumn)}
              options={getFilterOptions(activeFilterColumn)}
              onApply={handleApplyFilter}
              onClear={handleClearFilter}
              onClose={() => setActiveFilterColumn(null)}
            />
          )}

          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem' }}>
              <button className="btn-sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>&larr; Prev</button>
              <span style={{ fontSize: '0.85rem' }}>Page {page} of {totalPages}</span>
              <button className="btn-sm" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>Next &rarr;</button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default RatingsManager;
