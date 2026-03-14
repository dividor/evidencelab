import React, { useEffect, useState } from 'react';
import StarRating from './StarRating';

interface RatingModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Title shown in the modal header */
  title?: string;
  /** Initial score (0 = no selection) */
  initialScore?: number;
  /** Initial comment text */
  initialComment?: string;
  /** Called when the user submits a rating */
  onSubmit: (score: number, comment: string) => void;
  /** Called to delete a rating (only shown when initialScore > 0) */
  onDelete?: () => void;
}

const RatingModal: React.FC<RatingModalProps> = ({
  isOpen,
  onClose,
  title = 'Rate this item',
  initialScore = 0,
  initialComment = '',
  onSubmit,
  onDelete,
}) => {
  const [score, setScore] = useState(initialScore);
  const [comment, setComment] = useState(initialComment);

  useEffect(() => {
    setScore(initialScore);
    setComment(initialComment);
  }, [initialScore, initialComment, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (score === 0) return;
    onSubmit(score, comment.trim());
    onClose();
  };

  return (
    <div
      className="rating-modal-overlay"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
    >
      <div
        className="modal-panel rating-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 420, width: '90%' }}
      >
        <div className="modal-header">
          <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>{title}</h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">×</button>
          </div>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body" style={{ padding: '16px 20px' }}>
            <div style={{ marginBottom: 16, textAlign: 'center' }}>
              <StarRating score={score} onChange={setScore} size={28} />
              <div style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--brand-text-secondary)' }}>
                {score === 0 ? 'Click a star to rate' : `${score} / 5`}
              </div>
            </div>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional comment…"
              rows={3}
              maxLength={2000}
              style={{
                width: '100%',
                padding: '8px 10px',
                border: '1px solid var(--brand-border)',
                borderRadius: 6,
                resize: 'vertical',
                fontSize: '0.85rem',
                fontFamily: 'inherit',
              }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: onDelete && initialScore > 0 ? 'space-between' : 'flex-end',
              padding: '12px 20px',
              borderTop: '1px solid var(--brand-border-light)',
              gap: 8,
            }}
          >
            {onDelete && initialScore > 0 && (
              <button
                type="button"
                onClick={() => { onDelete(); onClose(); }}
                style={{
                  padding: '6px 14px',
                  fontSize: '0.82rem',
                  background: 'transparent',
                  color: 'var(--brand-error)',
                  border: '1px solid var(--brand-error)',
                  borderRadius: 6,
                  cursor: 'pointer',
                }}
              >
                Remove Rating
              </button>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '6px 14px',
                  fontSize: '0.82rem',
                  background: 'transparent',
                  color: 'var(--brand-text-secondary)',
                  border: '1px solid var(--brand-border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={score === 0}
                style={{
                  padding: '6px 14px',
                  fontSize: '0.82rem',
                  background: score === 0 ? 'var(--brand-border)' : 'var(--brand-primary)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: score === 0 ? 'not-allowed' : 'pointer',
                }}
              >
                Submit
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RatingModal;
