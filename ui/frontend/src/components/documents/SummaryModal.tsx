import React, { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { buildSummaryDisplayText } from './documentsModalUtils';
import { useAuth } from '../../hooks/useAuth';
import { useRatings } from '../../hooks/useRatings';
import StarRating from '../ratings/StarRating';
import RatingModal from '../ratings/RatingModal';
import { SummaryEditor } from './summary/SummaryEditor';
import type { SummaryAdmin } from './summary/useSummaryAdmin';

const MARKDOWN_COMPONENTS = {
  h1: ({ node, ...props }: any) => (
    <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
  ),
  h2: ({ node, ...props }: any) => (
    <h3 style={{ marginTop: '1.5rem', marginBottom: '0.8rem', color: '#1a1f36' }} {...props} />
  ),
  h3: ({ node, ...props }: any) => (
    <h4 style={{ marginTop: '1.2rem', marginBottom: '0.6rem', color: '#2c3b5a' }} {...props} />
  ),
  p: ({ node, ...props }: any) => <p style={{ marginBottom: '1rem', lineHeight: '1.6' }} {...props} />,
  ul: ({ node, ...props }: any) => <ul style={{ paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
  ol: ({ node, ...props }: any) => <ol style={{ paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
  li: ({ node, ...props }: any) => <li style={{ marginBottom: '0.4rem' }} {...props} />,
};

interface SummaryModalProps {
  isOpen: boolean;
  onClose: () => void;
  summary: string;
  title: string;
  /** Document ID used as the rating reference */
  docId?: string;
  /** Set for administrators on the Documents screen: edit and regenerate. */
  admin?: SummaryAdmin | null;
}

export const SummaryModal: React.FC<SummaryModalProps> = ({ isOpen, onClose, summary, title, docId, admin }) => {
  const { isAuthenticated } = useAuth();
  const { ratings, submitRating, deleteRating } = useRatings({
    ratingType: 'doc_summary',
    referenceId: docId || '',
    enabled: isAuthenticated && !!docId && isOpen,
  });
  const [ratingModalOpen, setRatingModalOpen] = useState(false);
  const [modalInitialScore, setModalInitialScore] = useState(0);

  const existing = ratings.get('');

  const handleSubmit = useCallback((score: number, comment: string) => {
    if (!docId) return;
    submitRating({
      ratingType: 'doc_summary',
      referenceId: docId,
      score,
      comment,
      context: {
        doc_id: docId,
        title,
        link: window.location.href,
        summary: summary || '',
      },
    });
  }, [docId, title, summary, submitRating]);

  const handleDelete = useCallback(() => {
    if (existing?.id) deleteRating(existing.id);
  }, [existing, deleteRating]);

  if (!isOpen) {
    return null;
  }

  const renderSummary = () => (
    <div className="summary-content markdown-content">
      <ReactMarkdown key="modal-summary" components={MARKDOWN_COMPONENTS}>
        {buildSummaryDisplayText(summary)}
      </ReactMarkdown>
    </div>
  );

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>
            {title}<em className="header-label-subtitle">(AI-generated : Experimental)</em>
          </h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">
              ×
            </button>
          </div>
        </div>
        <div className="modal-body">
          {admin && docId ? (
            <SummaryEditor key={docId} admin={admin} docId={docId} summary={summary} renderSummary={renderSummary} />
          ) : (
            renderSummary()
          )}
          {isAuthenticated && docId && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 6,
              marginTop: 12,
              paddingTop: 10,
              borderTop: '1px solid var(--brand-border-light)',
            }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--brand-text-tertiary)' }}>
                Rate this summary
              </span>
              <StarRating
                score={existing?.score || 0}
                onRequestModal={(selectedScore) => {
                  setModalInitialScore(existing?.score || selectedScore);
                  setRatingModalOpen(true);
                }}
                size={14}
              />
            </div>
          )}
        </div>
      </div>
      {ratingModalOpen && (
        <RatingModal
          isOpen={ratingModalOpen}
          onClose={() => setRatingModalOpen(false)}
          title="Rate this document summary"
          initialScore={modalInitialScore}
          initialComment={existing?.comment || ''}
          onSubmit={handleSubmit}
          onDelete={existing?.id ? handleDelete : undefined}
        />
      )}
    </div>
  );
};
