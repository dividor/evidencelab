import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';

interface AuditEntry {
  id: number;
  created_at: string;
  protocol: 'mcp' | 'a2a';
  tool_name: string;
  auth_type: string;
  user_id: string | null;
  client_ip: string | null;
  duration_ms: number | null;
  status: 'ok' | 'error';
  error_message: string | null;
  output_summary: string | null;
}

interface AuditResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

type ProtocolFilter = '' | 'mcp' | 'a2a';
type StatusFilter = '' | 'ok' | 'error';

const PROTOCOL_BADGE: Record<string, React.CSSProperties> = {
  mcp: { background: '#dbeafe', color: '#1d4ed8', border: '1px solid #93c5fd' },
  a2a: { background: '#f3e8ff', color: '#7e22ce', border: '1px solid #d8b4fe' },
};

const STATUS_BADGE: Record<string, React.CSSProperties> = {
  ok: { background: '#dcfce7', color: '#15803d', border: '1px solid #86efac' },
  error: { background: '#fee2e2', color: '#b91c1c', border: '1px solid #fca5a5' },
};

const badge = (style: React.CSSProperties, label: string) => (
  <span
    style={{
      ...style,
      fontSize: 11,
      fontWeight: 600,
      padding: '2px 7px',
      borderRadius: 10,
      whiteSpace: 'nowrap',
    }}
  >
    {label.toUpperCase()}
  </span>
);

const McpAuditLog: React.FC = () => {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [protocol, setProtocol] = useState<ProtocolFilter>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchAudit = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (protocol) params.protocol = protocol;
      if (statusFilter) params.status = statusFilter;
      const resp = await axios.get<AuditResponse>(`${API_BASE_URL}/mcp-audit/`, { params });
      setRows(resp.data.items);
      setTotal(resp.data.total);
    } catch {
      setError('Failed to load audit log');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, protocol, statusFilter]);

  useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [protocol, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const fmtDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const fmtMs = (ms: number | null) =>
    ms == null ? '—' : ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;

  return (
    <div className="admin-section">
      <h3>MCP / A2A Audit Log</h3>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 16 }}>
        All MCP tool calls and A2A task executions. Refreshes on filter change.
      </p>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div>
          <label style={{ fontSize: 12, color: '#6b7280', marginRight: 6 }}>Protocol</label>
          <select
            value={protocol}
            onChange={(e) => setProtocol(e.target.value as ProtocolFilter)}
            style={{ fontSize: 13, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db' }}
          >
            <option value="">All</option>
            <option value="mcp">MCP</option>
            <option value="a2a">A2A</option>
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, color: '#6b7280', marginRight: 6 }}>Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            style={{ fontSize: 13, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db' }}
          >
            <option value="">All</option>
            <option value="ok">OK</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 13, color: '#6b7280', alignSelf: 'center' }}>
          {total.toLocaleString()} entries
        </div>
      </div>

      {error && (
        <div className="auth-error" style={{ marginBottom: 12 }}>
          {error}
          <button onClick={() => setError('')} style={{ marginLeft: 8, cursor: 'pointer', border: 'none', background: 'none', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      {loading ? (
        <p style={{ color: '#6b7280' }}>Loading...</p>
      ) : rows.length === 0 ? (
        <p style={{ color: '#9ca3af', fontSize: 14 }}>No entries found.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Date</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Protocol</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Tool / Method</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Auth</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>User</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>IP</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Duration</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Status</th>
                <th style={{ padding: '8px 12px', color: '#374151', fontWeight: 600 }}>Summary / Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={row.id}
                  style={{
                    borderBottom: '1px solid #f3f4f6',
                    background: i % 2 === 0 ? '#fff' : '#fafafa',
                  }}
                >
                  <td style={{ padding: '8px 12px', whiteSpace: 'nowrap', color: '#6b7280' }}>{fmtDate(row.created_at)}</td>
                  <td style={{ padding: '8px 12px' }}>{badge(PROTOCOL_BADGE[row.protocol] || {}, row.protocol)}</td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{row.tool_name}</td>
                  <td style={{ padding: '8px 12px', color: '#6b7280' }}>{row.auth_type}</td>
                  <td style={{ padding: '8px 12px', color: '#6b7280', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.user_id || '—'}</td>
                  <td style={{ padding: '8px 12px', color: '#6b7280', fontFamily: 'monospace', fontSize: 12 }}>{row.client_ip || '—'}</td>
                  <td style={{ padding: '8px 12px', color: '#6b7280', whiteSpace: 'nowrap' }}>{fmtMs(row.duration_ms)}</td>
                  <td style={{ padding: '8px 12px' }}>{badge(STATUS_BADGE[row.status] || {}, row.status)}</td>
                  <td style={{ padding: '8px 12px', color: row.error_message ? '#b91c1c' : '#6b7280', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.error_message || row.output_summary || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 16, alignItems: 'center', justifyContent: 'center' }}>
          <button className="btn-sm btn-secondary" onClick={() => setPage(1)} disabled={page === 1}>«</button>
          <button className="btn-sm btn-secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
          <span style={{ fontSize: 13, color: '#6b7280' }}>Page {page} of {totalPages}</span>
          <button className="btn-sm btn-secondary" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>›</button>
          <button className="btn-sm btn-secondary" onClick={() => setPage(totalPages)} disabled={page === totalPages}>»</button>
        </div>
      )}
    </div>
  );
};

export default McpAuditLog;
