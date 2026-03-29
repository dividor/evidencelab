import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import ConfirmModal from './ConfirmModal';

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

const MASK = '••••••••••••••••••••••••••••••••••••••••';

const CopyButton: React.FC<{ value: string | null; disabled?: boolean }> = ({ value, disabled }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <button
      className="btn-sm btn-primary"
      onClick={handleCopy}
      disabled={disabled || !value}
      title="Copy key"
      style={{ height: 36, padding: '0 12px', display: 'flex', alignItems: 'center', gap: 4 }}
    >
      {copied ? 'Copied!' : 'Copy'}
    </button>
  );
};

const ApiKeyManager: React.FC = () => {
  const [currentKey, setCurrentKey] = useState<ApiKeyItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [generating, setGenerating] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [legacyKey, setLegacyKey] = useState<string | null>(undefined as unknown as null);
  const [legacyLoading, setLegacyLoading] = useState(true);

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

  const fetchLegacyKey = useCallback(async () => {
    try {
      const resp = await axios.get<{ key: string | null }>(`${API_BASE_URL}/api-keys/legacy`);
      setLegacyKey(resp.data.key);
    } catch {
      setLegacyKey(null);
    } finally {
      setLegacyLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKey();
    fetchLegacyKey();
  }, [fetchKey, fetchLegacyKey]);

  const generateKey = async () => {
    setError('');
    setGenerating(true);
    setRevealedKey(null);
    try {
      if (currentKey) {
        await axios.delete(`${API_BASE_URL}/api-keys/${currentKey.id}`);
      }
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
  const canCopy = !!revealedKey;

  return (
    <div className="admin-section">
      <h3>API Key</h3>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 16 }}>
        Use this key to authenticate API and MCP requests via the <code>X-API-Key</code> header.
      </p>

      {error && (
        <div className="auth-error" style={{ marginBottom: 12 }}>
          {error}
          <button onClick={() => setError('')} style={{ marginLeft: 8, cursor: 'pointer', border: 'none', background: 'none', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 600 }}>
        <input
          type="text"
          readOnly
          value={displayValue}
          placeholder="No API key generated"
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
        <CopyButton value={revealedKey} disabled={!canCopy} />
        <button
          className="btn-sm btn-primary"
          onClick={() => currentKey ? setShowConfirm(true) : generateKey()}
          disabled={generating}
          style={{ height: 36, padding: '0 12px', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          {generating ? 'Generating...' : currentKey ? 'Regenerate' : 'Generate'}
        </button>
      </div>

      {revealedKey && (
        <p style={{ color: '#d97706', fontSize: 13, marginTop: 8 }}>
          Copy this key now — it will not be shown again after you leave this page.
        </p>
      )}

      {!revealedKey && currentKey && (
        <p style={{ color: '#9ca3af', fontSize: 12, marginTop: 8 }}>
          Full key is not retrievable after creation. Regenerate to get a new copyable key.
          {' '}Created {new Date(currentKey.created_at).toLocaleDateString()}
          {currentKey.created_by_email && ` by ${currentKey.created_by_email}`}
        </p>
      )}

      {!legacyLoading && legacyKey && (
        <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid #e5e7eb' }}>
          <h4 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 600 }}>Legacy API Key (env)</h4>
          <p style={{ color: '#6b7280', fontSize: 13, marginBottom: 12 }}>
            Set via the <code>API_KEY</code> environment variable. This key continues to work alongside any generated keys above.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 600 }}>
            <input
              type="text"
              readOnly
              value={legacyKey}
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
            <CopyButton value={legacyKey} />
          </div>
        </div>
      )}

      {showConfirm && (
        <ConfirmModal
          title="Regenerate API Key"
          message="This will revoke the current key and generate a new one. Any applications using the current key will lose access. Continue?"
          confirmLabel="Regenerate"
          onConfirm={() => { setShowConfirm(false); generateKey(); }}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
};

export default ApiKeyManager;
