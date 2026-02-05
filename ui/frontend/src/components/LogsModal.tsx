import React from 'react';
import { useDocumentLogs } from '../hooks/useDocumentLogs';

interface LogsModalProps {
  isOpen: boolean;
  onClose: () => void;
  docId: string;
  docTitle: string;
  dataSource: string;
}

const LogsModal: React.FC<LogsModalProps> = ({
  isOpen,
  onClose,
  docId,
  docTitle,
  dataSource,
}) => {
  const { logs, loading, error } = useDocumentLogs({
    isOpen,
    docId,
    dataSource
  });

  if (!isOpen) return null;

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel logs-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Processing Logs</h2>
          <button onClick={onClose} className="modal-close">×</button>
        </div>
        <div className="modal-body">
          <div className="logs-doc-title">{docTitle || 'Untitled'}</div>
          {loading && (
            <div className="logs-loading">Loading logs...</div>
          )}
          {error && (
            <div className="logs-error">
              <strong>Error:</strong> {error}
            </div>
          )}
          {!loading && !error && (
            <div className="logs-content">
              {logs ? (
                <pre className="logs-text">{logs}</pre>
              ) : (
                <div className="logs-empty">No logs available for this document.</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default LogsModal;
