import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import StarRating from '../ratings/StarRating';

interface FeedbackModalProps {
  isOpen: boolean;
  onClose: () => void;
  url: string;
  screenshot: string | null;
  screenshotError: string | null;
}

// Server enforces a 1 MB cap on the JSONB `context` column. Leave a little
// headroom for the rest of the payload so we never trip a 422.
const MAX_SCREENSHOT_BYTES = 950_000;

const FONT_SIZE_HINT = '0.78rem';
const FONT_SIZE_BUTTON = '0.82rem';
const BORDER_DEFAULT = '1px solid var(--brand-border)';
const BUTTON_PADDING = '6px 14px';
const COLOR_TEXT_SECONDARY = 'var(--brand-text-secondary)';
const COLOR_ERROR = 'var(--brand-error)';
const COLOR_PRIMARY = 'var(--brand-primary)';
const COLOR_BORDER = 'var(--brand-border)';
const RADIUS_DEFAULT = 6;

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

// Keep Tab and Shift+Tab inside the dialog so focus can't reach the page
// behind the overlay.
const trapTab = (e: KeyboardEvent, panel: HTMLElement) => {
  const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
  if (items.length === 0) {
    e.preventDefault();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  const startingFromPanelOrPage = active === panel || !panel.contains(active);
  if (e.shiftKey && (active === first || startingFromPanelOrPage)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (active === last || startingFromPanelOrPage)) {
    e.preventDefault();
    first.focus();
  }
};

const FeedbackModal: React.FC<FeedbackModalProps> = ({
  isOpen,
  onClose,
  url,
  screenshot,
  screenshotError,
}) => {
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!isOpen) return undefined;
    panelRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeRef.current();
      } else if (e.key === 'Tab' && panelRef.current) {
        trapTab(e, panelRef.current);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isOpen]);

  if (!isOpen) return null;

  const screenshotTooLarge =
    screenshot !== null && screenshot.length > MAX_SCREENSHOT_BYTES;
  const canSubmit = score >= 1 && comment.trim().length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const context: Record<string, unknown> = {};
      if (screenshot && !screenshotTooLarge) context.screenshot = screenshot;
      if (screenshotError) context.screenshot_error = screenshotError;
      await axios.post(`${API_BASE_URL}/ratings/`, {
        rating_type: 'page_feedback',
        reference_id: url.slice(0, 255),
        score,
        comment: comment.trim(),
        url,
        context: Object.keys(context).length > 0 ? context : null,
      });
      setSubmitted(true);
    } catch (err: unknown) {
      const responseData = (err as { response?: { data?: unknown } } | null)?.response?.data;
      setSubmitError(responseData ? JSON.stringify(responseData) : 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setScore(0);
    setComment('');
    setSubmitError(null);
    setSubmitted(false);
    onClose();
  };
  closeRef.current = handleClose;

  return (
    <div
      className="rating-modal-overlay"
      onClick={handleClose}
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
        ref={panelRef}
        className="modal-panel feedback-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-modal-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 420, width: '92%' }}
      >
        <div className="modal-header">
          <h2 id="feedback-modal-title" style={{ fontSize: '1rem', fontWeight: 600 }}>Send feedback</h2>
          <div className="modal-header-actions">
            <button onClick={handleClose} className="modal-close" aria-label="Close">×</button>
          </div>
        </div>

        {submitted ? (
          <div className="modal-body" style={{ padding: '24px 20px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: '0.9rem' }}>Thanks — your feedback was submitted.</p>
            <button
              type="button"
              onClick={handleClose}
              style={{
                marginTop: 16,
                padding: BUTTON_PADDING,
                fontSize: FONT_SIZE_BUTTON,
                background: COLOR_PRIMARY,
                color: '#fff',
                border: 'none',
                borderRadius: RADIUS_DEFAULT,
                cursor: 'pointer',
              }}
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="modal-body" style={{ padding: '16px 20px' }}>
              <div style={{ marginBottom: 16, textAlign: 'center' }}>
                <StarRating score={score} onChange={setScore} size={28} />
                <div style={{ marginTop: 6, fontSize: FONT_SIZE_HINT, color: COLOR_TEXT_SECONDARY }}>
                  {score === 0 ? 'Click a star to rate' : `${score} / 5`}
                </div>
              </div>

              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Tell us what went well or what needs improvement…"
                rows={4}
                maxLength={2000}
                required
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  border: BORDER_DEFAULT,
                  borderRadius: RADIUS_DEFAULT,
                  resize: 'vertical',
                  fontSize: '0.85rem',
                  fontFamily: 'inherit',
                }}
              />

              <div
                style={{
                  marginTop: 10,
                  fontSize: FONT_SIZE_HINT,
                  color: COLOR_TEXT_SECONDARY,
                }}
              >
                {screenshot && !screenshotTooLarge && '✓ Screenshot attached'}
                {screenshotTooLarge && '⚠ Screenshot was too large to attach'}
                {screenshotError && `⚠ Screenshot capture failed: ${screenshotError}`}
                {!screenshot && !screenshotError && '… capturing screenshot'}
              </div>

              {submitError && (
                <p style={{ margin: '8px 0 0', color: COLOR_ERROR, fontSize: FONT_SIZE_HINT }}>
                  {submitError}
                </p>
              )}
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                padding: '12px 20px',
                borderTop: '1px solid var(--brand-border-light)',
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={handleClose}
                disabled={submitting}
                style={{
                  padding: BUTTON_PADDING,
                  fontSize: FONT_SIZE_BUTTON,
                  background: 'transparent',
                  color: COLOR_TEXT_SECONDARY,
                  border: BORDER_DEFAULT,
                  borderRadius: RADIUS_DEFAULT,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !canSubmit}
                style={{
                  padding: BUTTON_PADDING,
                  fontSize: FONT_SIZE_BUTTON,
                  background: submitting || !canSubmit ? COLOR_BORDER : COLOR_PRIMARY,
                  color: '#fff',
                  border: 'none',
                  borderRadius: RADIUS_DEFAULT,
                  cursor: submitting || !canSubmit ? 'not-allowed' : 'pointer',
                }}
              >
                {submitting ? 'Submitting…' : 'Submit'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

export default FeedbackModal;
