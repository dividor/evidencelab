import React, { useCallback, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useRatings } from '../../hooks/useRatings';
import StarRating from '../ratings/StarRating';
import RatingModal from '../ratings/RatingModal';

interface TaxonomyValue {
  code: string;
  name: string;
  reason?: string;
}

interface TaxonomyModalProps {
  isOpen: boolean;
  onClose: () => void;
  taxonomyValue: TaxonomyValue | null;
  definition: string;
  taxonomyName: string;
  /** Document ID used as rating reference */
  docId?: string;
  /** Document title for rating context */
  docTitle?: string;
  /** Document AI summary for rating context */
  docSummary?: string;
}

export const TaxonomyModal: React.FC<TaxonomyModalProps> = ({
  isOpen,
  onClose,
  taxonomyValue,
  definition,
  taxonomyName,
  docId,
  docTitle,
  docSummary,
}) => {
  const { isAuthenticated } = useAuth();
  const { ratings, submitRating, deleteRating } = useRatings({
    ratingType: 'taxonomy',
    referenceId: docId || '',
    enabled: isAuthenticated && !!docId && isOpen,
  });
  const [ratingModalOpen, setRatingModalOpen] = useState(false);
  const [modalInitialScore, setModalInitialScore] = useState(0);

  const itemId = taxonomyValue?.code || '';
  const existing = ratings.get(itemId);

  const handleSubmit = useCallback((score: number, comment: string) => {
    if (!docId || !taxonomyValue) return;
    submitRating({
      ratingType: 'taxonomy',
      referenceId: docId,
      itemId: taxonomyValue.code,
      score,
      comment,
      context: {
        doc_id: docId,
        title: docTitle || '',
        link: window.location.href,
        summary: docSummary || '',
        taxonomy_type: taxonomyName,
        taxonomy_value: `${taxonomyValue.code} - ${taxonomyValue.name || ''}`.trim(),
        code: taxonomyValue.code,
        name: taxonomyValue.name,
        reason: taxonomyValue.reason,
      },
    });
  }, [docId, docTitle, docSummary, taxonomyValue, taxonomyName, submitRating]);

  const handleDelete = useCallback(() => {
    if (existing?.id) deleteRating(existing.id);
  }, [existing, deleteRating]);

  if (!isOpen || !taxonomyValue) {
    return null;
  }

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>
            {taxonomyValue.code.toUpperCase()}
            {taxonomyValue.name ? ` - ${taxonomyValue.name}` : ''}
            <em className="header-label-subtitle">(AI-generated : Experimental)</em>
          </h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">
              ×
            </button>
          </div>
        </div>
        <div className="modal-body">
          <div className="taxonomy-content">
            {definition && (
              <section style={{ marginBottom: '1.5rem' }}>
                <h3 style={{
                  fontSize: '1rem',
                  fontWeight: 600,
                  marginBottom: '0.5rem',
                  color: '#1a1f36'
                }}>
                  Definition
                </h3>
                <p style={{
                  lineHeight: '1.6',
                  color: '#4a5568'
                }}>
                  {definition}
                </p>
              </section>
            )}

            {taxonomyValue.reason && (
              <section>
                <h3 style={{
                  fontSize: '1rem',
                  fontWeight: 600,
                  marginBottom: '0.5rem',
                  color: '#1a1f36'
                }}>
                  Why this {taxonomyName} was assigned
                </h3>
                <p style={{
                  fontStyle: 'italic',
                  color: '#666',
                  lineHeight: '1.6',
                  background: '#f7fafc',
                  padding: '1rem',
                  borderRadius: '6px',
                  borderLeft: '3px solid #0369a1'
                }}>
                  {taxonomyValue.reason}
                </p>
                <p style={{
                  fontSize: '0.875rem',
                  color: '#999',
                  marginTop: '0.5rem'
                }}>
                  AI-generated explanation
                </p>
              </section>
            )}
          </div>
          {isAuthenticated && docId && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 6,
              marginTop: 16,
              paddingTop: 12,
              borderTop: '1px solid var(--brand-border-light)',
            }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--brand-text-tertiary)' }}>
                Rate this taxonomy tag
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
          title={`Rate: ${taxonomyValue.code.toUpperCase()}`}
          initialScore={modalInitialScore}
          initialComment={existing?.comment || ''}
          onSubmit={handleSubmit}
          onDelete={existing?.id ? handleDelete : undefined}
        />
      )}
    </div>
  );
};
