import React, { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';

interface HeatmapInfoModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const HeatmapInfoModal: React.FC<HeatmapInfoModalProps> = ({ isOpen, onClose }) => {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && content === null) {
      fetch(`${process.env.PUBLIC_URL}/docs/heatmapper.md`)
        .then((res) => res.text())
        .then(setContent)
        .catch(() => setContent('Unable to load documentation.'));
    }
  }, [isOpen, content]);

  const stopPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

  if (!isOpen) return null;

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={stopPropagation}>
        <div className="modal-header">
          <h2>What is Heatmapper?</h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">
              &times;
            </button>
          </div>
        </div>
        <div className="modal-body">
          <div className="markdown-content">
            {content ? (
              <ReactMarkdown
                components={{
                  h1: ({ node, ...props }) => (
                    <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
                  ),
                  h2: ({ node, ...props }) => (
                    <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
                  ),
                  p: ({ node, ...props }) => <p style={{ marginBottom: '1rem', lineHeight: '1.6' }} {...props} />,
                  ul: ({ node, ...props }) => <ul style={{ paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
                  li: ({ node, ...props }) => <li style={{ marginBottom: '0.4rem' }} {...props} />,
                }}
              >
                {content}
              </ReactMarkdown>
            ) : (
              <p>Loading...</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
