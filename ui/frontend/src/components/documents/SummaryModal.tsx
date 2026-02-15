import React from 'react';
import ReactMarkdown from 'react-markdown';
import { buildSummaryDisplayText } from './documentsModalUtils';

interface SummaryModalProps {
  isOpen: boolean;
  onClose: () => void;
  summary: string;
  title: string;
}

export const SummaryModal: React.FC<SummaryModalProps> = ({ isOpen, onClose, summary, title }) => {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}<em className="header-label-subtitle">(AI-generated : Experimental)</em></h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">
              ×
            </button>
          </div>
        </div>
        <div className="modal-body">
          <div className="summary-content markdown-content">
            <ReactMarkdown
              key="modal-summary"
              components={{
                h1: ({ node, ...props }) => (
                  <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
                ),
                h2: ({ node, ...props }) => (
                  <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
                ),
                h3: ({ node, ...props }) => (
                  <h4 style={{ marginTop: '1.2rem', marginBottom: '0.6rem', color: '#2c3b5a' }} {...props} />
                ),
                p: ({ node, ...props }) => <p style={{ marginBottom: '1rem', lineHeight: '1.6' }} {...props} />,
                ul: ({ node, ...props }) => <ul style={{ paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
                ol: ({ node, ...props }) => <ol style={{ paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
                li: ({ node, ...props }) => <li style={{ marginBottom: '0.4rem' }} {...props} />,
              }}
            >
              {buildSummaryDisplayText(summary)}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
};
