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

const MASK = '**************************************';

const ApiKeyManager: React.FC = () => {
  const [currentKey, setCurrentKey] = useState<ApiKeyItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [generating, setGenerating] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

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
    setCopied(false);
    try {
      // Revoke existing key first if one exists
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

  const handleGenerate = () => {
    if (currentKey) {
      setShowConfirm(true);
    } else {
      generateKey();
    }
  };

  const handleCopy = async () => {
    if (!revealedKey) return;
    try {
      await navigator.clipboard.writeText(revealedKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Failed to copy to clipboard');
    }
  };

  if (loading) return <p>Loading...</p>;

  const displayValue = revealedKey || (currentKey ? MASK : '');

  return (
    <div className="admin-section">
      <h3>API Key</h3>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 16 }}>
        Use this key to authenticate API requests via the <code>X-API-Key</code> header.
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
        <button
          className="btn-sm btn-primary"
          onClick={handleCopy}
          disabled={!revealedKey}
          title="Copy key"
          style={{ height: 36, padding: '0 12px', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button
          className="btn-sm btn-primary"
          onClick={handleGenerate}
          disabled={generating}
          title={currentKey ? 'Regenerate key' : 'Generate key'}
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

      {currentKey && (
        <p style={{ color: '#9ca3af', fontSize: 12, marginTop: 8 }}>
          Created {new Date(currentKey.created_at).toLocaleDateString()}
          {currentKey.created_by_email && ` by ${currentKey.created_by_email}`}
        </p>
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
