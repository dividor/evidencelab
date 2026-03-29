import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL, { API_KEY as LEGACY_API_KEY } from '../../config';

interface ApiKeyItem {
  id: string;
  label: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  created_by_email: string | null;
  last_used_at: string | null;
}

interface CreatedKey extends ApiKeyItem {
  key: string;
}

const MASK = '**************************************';

const CopyButton: React.FC<{ value: string | null | undefined; label?: string }> = ({ value, label = 'Copy' }) => {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');

  const handleCopy = async () => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Failed to copy');
      setTimeout(() => setError(''), 2000);
    }
  };

  return (
    <button
      className="btn-sm btn-primary"
      onClick={handleCopy}
      disabled={!value}
      title={value ? 'Copy to clipboard' : 'Nothing to copy'}
      style={{ height: 36, padding: '0 12px', display: 'flex', alignItems: 'center', gap: 4 }}
    >
      {error || (copied ? 'Copied!' : label)}
    </button>
  );
};

const ApiKeyManager: React.FC = () => {
  const [currentKey, setCurrentKey] = useState<ApiKeyItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [generating, setGenerating] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const fetchKey = useCallback(async () => {
    try {
      const resp = await axios.get<ApiKeyItem[]>(`${API_BASE_URL}/api-keys/`);
      const activeKeys = resp.data.filter((k) => k.is_active);
      setCurrentKey(activeKeys.length > 0 ? activeKeys[0] : null);
    } catch {
      setError('Failed to load API key');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKey();
  }, [fetchKey]);

  const generateKey = async () => {
    setError('');
    setGenerating(true);
    try {
      const resp = await axios.post<CreatedKey>(`${API_BASE_URL}/api-keys/`, { label: 'API Key' });
      setRevealedKey(resp.data.key);
      await fetchKey();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate API key');
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return <p>Loading...</p>;

  const displayValue = revealedKey || (currentKey ? `${currentKey.key_prefix}${MASK}` : '');
  const copyValue = revealedKey || currentKey?.key_prefix || null;

  return (
    <div className="admin-section">
      <h3>API Keys</h3>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 16 }}>
        Use these keys to authenticate API and MCP requests via the <code>X-API-Key</code> header.
      </p>

      {error && (
        <div className="auth-error" style={{ marginBottom: 12 }}>
          {error}
          <button onClick={() => setError('')} style={{ marginLeft: 8, cursor: 'pointer', border: 'none', background: 'none', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      {/* DB-backed key */}
      <div style={{ marginBottom: 24 }}>
        <p style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Generated Key</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 600 }}>
          <input
            type="text"
            readOnly
            value={displayValue}
            placeholder="No API key generated yet"
            style={{
              flex: 1,
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: 4,
              fontSize: 14,
              fontFamily: 'monospace',
              background: '#f9fafb',
              color: revealedKey ? '#111827' : '#6b7280',
            }}
          />
          <CopyButton value={copyValue} />
          {!currentKey && (
            <button
              className="btn-sm btn-primary"
              onClick={generateKey}
              disabled={generating}
              style={{ height: 36, padding: '0 12px', display: 'flex', alignItems: 'center', gap: 4 }}
            >
              {generating ? 'Generating...' : 'Generate'}
            </button>
          )}
        </div>
        {revealedKey && (
          <p style={{ color: '#d97706', fontSize: 13, marginTop: 8 }}>
            Copy this key now — the full key will not be shown again after you leave this page.
          </p>
        )}
        {currentKey && !revealedKey && (
          <p style={{ color: '#9ca3af', fontSize: 12, marginTop: 8 }}>
            Showing key prefix only. Created {new Date(currentKey.created_at).toLocaleDateString()}
            {currentKey.created_by_email && ` by ${currentKey.created_by_email}`}
          </p>
        )}
      </div>

      {/* Legacy env-based key */}
      {LEGACY_API_KEY && (
        <div>
          <p style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Legacy Key</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 600 }}>
            <input
              type="text"
              readOnly
              value={LEGACY_API_KEY}
              style={{
                flex: 1,
                padding: '8px 12px',
                border: '1px solid #d1d5db',
                borderRadius: 4,
                fontSize: 14,
                fontFamily: 'monospace',
                background: '#f9fafb',
                color: '#111827',
              }}
            />
            <CopyButton value={LEGACY_API_KEY} />
          </div>
          <p style={{ color: '#9ca3af', fontSize: 12, marginTop: 8 }}>
            Static key set via <code>REACT_APP_API_KEY</code> in environment config.
          </p>
        </div>
      )}
    </div>
  );
};

export default ApiKeyManager;
