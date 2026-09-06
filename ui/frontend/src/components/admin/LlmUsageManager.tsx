import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { SortableHeader } from '../documents/SortableHeader';

// ---------------------------------------------------------------------------
// Types — match the /llm-usage/summary response shape from the backend.
// ---------------------------------------------------------------------------

type Bucket = 'day' | 'week' | 'month';
type GroupBy = 'user' | 'user_group';

interface UsageRow {
  bucket_start: string;
  group_key: string;
  group_label: string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  // cost_usd is a Decimal serialized as a string (preserves micro-dollar precision).
  cost_usd: string | null;
}

interface UsageResponse {
  rows: UsageRow[];
  totals: {
    request_count: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd: string;
  };
  bucket: Bucket;
  group_by: GroupBy;
  from_date: string;
  to_date: string;
  activity_type: string | null;
}

const ACTIVITY_TYPES: ReadonlyArray<{ value: string; label: string }> = [
  { value: '', label: 'All' },
  { value: 'search', label: 'Search' },
  { value: 'heatmap', label: 'Heatmap' },
  { value: 'chat', label: 'Chat' },
  { value: 'assistant-basic', label: 'Assistant (basic)' },
  { value: 'assistant-deep-research', label: 'Assistant (deep)' },
  { value: 'brief', label: 'Brief' },
  { value: 'highlight', label: 'Highlighting' },
  { value: 'evaluation', label: 'Evaluations' },
  { value: 'mcp-assistant', label: 'MCP assistant' },
  { value: 'a2a-assistant', label: 'A2A assistant' },
  { value: 'pipeline', label: 'Pipeline' },
];

const NULL_CELL = '—';
const BORDER_LIGHT = '1px solid #ccc';

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const formatTokens = (n: number): string => n.toLocaleString();

const formatCost = (cost: string | null): string => {
  if (cost == null) return NULL_CELL;
  const n = parseFloat(cost);
  if (!Number.isFinite(n)) return NULL_CELL;
  return `$${n.toFixed(6)}`;
};

const isoToday = (): string => new Date().toISOString().slice(0, 10);
const isoNDaysAgo = (n: number): string => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
};

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

interface ControlsProps {
  bucket: Bucket;
  groupBy: GroupBy;
  fromDate: string;
  toDate: string;
  activityType: string;
  onBucketChange: (b: Bucket) => void;
  onGroupByChange: (g: GroupBy) => void;
  onFromDateChange: (d: string) => void;
  onToDateChange: (d: string) => void;
  onActivityTypeChange: (t: string) => void;
  onExport: () => void;
  exporting: boolean;
}

const Controls: React.FC<ControlsProps> = ({
  bucket,
  groupBy,
  fromDate,
  toDate,
  activityType,
  onBucketChange,
  onGroupByChange,
  onFromDateChange,
  onToDateChange,
  onActivityTypeChange,
  onExport,
  exporting,
}) => {
  const radio = (
    name: string,
    value: string,
    current: string,
    label: string,
    onChange: () => void,
  ) => (
    <label style={{ marginRight: 12, fontSize: '0.85rem' }}>
      <input
        type="radio"
        name={name}
        value={value}
        checked={current === value}
        onChange={onChange}
        style={{ marginRight: 4 }}
      />
      {label}
    </label>
  );

  return (
    <div
      className="admin-controls"
      style={{
        display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '0.75rem',
        flexWrap: 'wrap',
      }}
    >
      <div>
        <span style={{ fontSize: '0.8rem', color: '#555', marginRight: 6 }}>Bucket:</span>
        {radio('bucket', 'day', bucket, 'Day', () => onBucketChange('day'))}
        {radio('bucket', 'week', bucket, 'Week', () => onBucketChange('week'))}
        {radio('bucket', 'month', bucket, 'Month', () => onBucketChange('month'))}
      </div>
      <div>
        <span style={{ fontSize: '0.8rem', color: '#555', marginRight: 6 }}>Group by:</span>
        {radio('groupBy', 'user', groupBy, 'User', () => onGroupByChange('user'))}
        {radio('groupBy', 'user_group', groupBy, 'Group', () => onGroupByChange('user_group'))}
      </div>
      <div>
        <label style={{ fontSize: '0.8rem', color: '#555', marginRight: 4 }}>From:</label>
        <input
          type="date"
          value={fromDate}
          onChange={(e) => onFromDateChange(e.target.value)}
          style={{ padding: '0.3rem', borderRadius: 4, border: BORDER_LIGHT, fontSize: '0.85rem' }}
        />
        <label style={{ fontSize: '0.8rem', color: '#555', marginLeft: 8, marginRight: 4 }}>To:</label>
        <input
          type="date"
          value={toDate}
          onChange={(e) => onToDateChange(e.target.value)}
          style={{ padding: '0.3rem', borderRadius: 4, border: BORDER_LIGHT, fontSize: '0.85rem' }}
        />
      </div>
      <div>
        <label style={{ fontSize: '0.8rem', color: '#555', marginRight: 4 }}>Activity type:</label>
        <select
          value={activityType}
          onChange={(e) => onActivityTypeChange(e.target.value)}
          style={{ padding: '0.3rem', borderRadius: 4, border: BORDER_LIGHT, fontSize: '0.85rem' }}
        >
          {ACTIVITY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>
      <button
        className="admin-download-button"
        onClick={onExport}
        disabled={exporting}
        style={{ marginLeft: 'auto' }}
      >
        {exporting ? 'Downloading...' : 'Download XLSX'}
      </button>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const LlmUsageManager: React.FC = () => {
  const [bucket, setBucket] = useState<Bucket>('week');
  const [groupBy, setGroupBy] = useState<GroupBy>('user');
  const [fromDate, setFromDate] = useState<string>(isoNDaysAgo(30));
  const [toDate, setToDate] = useState<string>(isoToday());
  const [activityType, setActivityType] = useState<string>('');

  const [data, setData] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('bucket_start');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [exporting, setExporting] = useState(false);

  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      bucket,
      group_by: groupBy,
      from_date: fromDate,
      to_date: toDate,
      sort_by: sortBy,
      order,
    };
    if (activityType) params.activity_type = activityType;
    return params;
  }, [bucket, groupBy, fromDate, toDate, sortBy, order, activityType]);

  const fetchUsage = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await axios.get<UsageResponse>(
        `${API_BASE_URL}/llm-usage/summary`,
        { params: queryParams },
      );
      setData(resp.data);
    } catch (e) {
      console.error('LLM usage fetch failed', e);
      setError('Failed to load LLM usage');
    } finally {
      setLoading(false);
    }
  }, [queryParams]);

  useEffect(() => { fetchUsage(); }, [fetchUsage]);

  const handleSort = (col: string) => {
    if (sortBy === col) setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(col); setOrder('desc'); }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const resp = await axios.get<Blob>(
        `${API_BASE_URL}/llm-usage/export`,
        { params: queryParams, responseType: 'blob' },
      );
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `llm_usage_${groupBy}_${bucket}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError('Export failed');
    } finally {
      setExporting(false);
    }
  };

  const rows = data?.rows ?? [];
  const totals = data?.totals;
  const groupColLabel = groupBy === 'user' ? 'User' : 'Group';

  // This tab uses dedicated controls (bucket / groupBy / dates / type) above
  // the table rather than per-column filter popovers, so the SortableHeader
  // filter props get no-op stubs.
  const noFilterClick = () => {};
  const noActiveFilter = () => false;

  return (
    <div className="admin-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <Controls
        bucket={bucket}
        groupBy={groupBy}
        fromDate={fromDate}
        toDate={toDate}
        activityType={activityType}
        onBucketChange={setBucket}
        onGroupByChange={setGroupBy}
        onFromDateChange={setFromDate}
        onToDateChange={setToDate}
        onActivityTypeChange={setActivityType}
        onExport={handleExport}
        exporting={exporting}
      />

      {groupBy === 'user_group' && (
        <p className="text-muted" style={{ fontSize: '0.78rem', marginBottom: '0.5rem' }}>
          Note: a user in multiple groups contributes to every group they belong to,
          so summing the cost across rows over-counts shared users.
        </p>
      )}

      {loading ? (
        <div className="admin-loading">Loading usage...</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="admin-table">
            <thead>
              <tr>
                <SortableHeader columnKey="bucket_start" label={`Bucket (${bucket})`}
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="group_label" label={groupColLabel}
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="request_count" label="Requests"
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="prompt_tokens" label="Prompt tokens"
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="completion_tokens" label="Completion tokens"
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="total_tokens" label="Total tokens"
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
                <SortableHeader columnKey="cost_usd" label="Cost (USD)"
                  sortField={sortBy} sortDirection={order} onSort={handleSort}
                  onFilterClick={noFilterClick} hasActiveFilter={noActiveFilter} />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '1.5rem', color: '#888' }}>
                    No usage in the selected range
                  </td>
                </tr>
              ) : (
                rows.map((r, i) => (
                  <tr key={`${r.bucket_start}|${r.group_key}|${i}`}>
                    <td style={{ whiteSpace: 'nowrap', fontSize: '0.82rem' }}>{r.bucket_start}</td>
                    <td style={{ fontSize: '0.82rem' }}>{r.group_label}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                      {formatTokens(r.request_count)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                      {formatTokens(r.prompt_tokens)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                      {formatTokens(r.completion_tokens)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                      {formatTokens(r.total_tokens)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                      {formatCost(r.cost_usd)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
            {totals && rows.length > 0 && (
              <tfoot>
                <tr style={{ fontWeight: 600, background: '#f8f9fa' }}>
                  <td style={{ fontSize: '0.82rem' }}>Total</td>
                  <td></td>
                  <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                    {formatTokens(totals.request_count)}
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                    {formatTokens(totals.prompt_tokens)}
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                    {formatTokens(totals.completion_tokens)}
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                    {formatTokens(totals.total_tokens)}
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.82rem' }}>
                    {formatCost(totals.cost_usd)}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
};

export default LlmUsageManager;
