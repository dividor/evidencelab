import React, { useState } from 'react';
import html2canvas from 'html2canvas';
import FeedbackModal from './FeedbackModal';

const TOOLTIP = 'Send feedback about this page';

// Server allows up to ~1 MB JSONB; leave ~10% headroom for the rest of the
// payload (rating_type, comment, url, JSON overhead).
const SCREENSHOT_BYTES_BUDGET = 900_000;
const JPEG_QUALITY_LADDER = [0.6, 0.4, 0.25];

const OVERLAY_CLASS_PATTERN =
  /(overlay|backdrop|drawer|dropdown-menu|loading|spinner|tooltip|popover|toast|snackbar)/i;

const shouldIgnoreForCapture = (el: Element): boolean => {
  const cls = typeof el.className === 'string' ? el.className : '';
  if (OVERLAY_CLASS_PATTERN.test(cls)) return true;
  if (el.getAttribute('aria-modal') === 'true') return true;
  const role = el.getAttribute('role');
  if (role === 'dialog' || role === 'tooltip') return true;
  const cs = window.getComputedStyle(el);
  return (
    (cs.position === 'fixed' || cs.position === 'sticky') &&
    parseFloat(cs.opacity) < 1
  );
};

// Speech-bubble icon — communicates "leave a comment" without needing a label.
const FeedbackIcon: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const FeedbackButton: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  const [url, setUrl] = useState('');

  const handleOpen = async () => {
    setCapturing(true);
    setScreenshot(null);
    setScreenshotError(null);
    setUrl(window.location.href);

    try {
      const canvas = await html2canvas(document.documentElement, {
        scale: 0.5,
        logging: false,
        useCORS: true,
        backgroundColor: '#ffffff',
        // Crop to the viewport so the screenshot shows only what the user
        // sees, not the entire scrollable document.
        width: window.innerWidth,
        height: window.innerHeight,
        x: window.scrollX,
        y: window.scrollY,
        // Skip translucent overlays (loading spinners, modal backdrops,
        // side panels, dropdowns) so the captured screenshot shows the
        // underlying page rather than a faded/tinted version masked by
        // whatever overlay was on screen.
        ignoreElements: shouldIgnoreForCapture,
        // The cloned DOM is rendered fresh in an iframe, so any
        // opacity:0 → opacity:1 fade-in animation restarts from frame 0
        // and html2canvas snapshots elements mid-fade. Disable all
        // animations/transitions in the clone so they render at their
        // final state.
        onclone: (clonedDoc) => {
          const style = clonedDoc.createElement('style');
          style.textContent =
            '*,*::before,*::after{animation:none!important;transition:none!important}';
          clonedDoc.head.appendChild(style);
        },
      });
      // Try progressively lower JPEG quality until the encoded URL fits the
      // server's JSONB budget. Big or busy pages fall back to lower quality
      // rather than dropping the screenshot entirely.
      let chosen: string | null = null;
      let lastSize = 0;
      for (const quality of JPEG_QUALITY_LADDER) {
        const dataUrl = canvas.toDataURL('image/jpeg', quality);
        if (!dataUrl || dataUrl === 'data:,' || dataUrl.length < 100) continue;
        lastSize = dataUrl.length;
        if (dataUrl.length <= SCREENSHOT_BYTES_BUDGET) {
          chosen = dataUrl;
          break;
        }
      }
      if (chosen) {
        setScreenshot(chosen);
      } else if (lastSize === 0) {
        setScreenshotError('canvas was empty');
      } else {
        setScreenshotError(
          `screenshot too large to attach (${Math.round(lastSize / 1024)} KB at lowest quality)`,
        );
      }
    } catch (err: unknown) {
      setScreenshotError(err instanceof Error ? err.message : 'unknown error');
    } finally {
      setCapturing(false);
      setOpen(true);
    }
  };

  const handleClose = () => {
    setOpen(false);
    setScreenshot(null);
    setScreenshotError(null);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        disabled={capturing}
        aria-label={TOOLTIP}
        title={TOOLTIP}
        style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 9000,
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          // Match the Search button (--brand-accent) so both share the brand color.
          background: 'var(--brand-accent, #475569)',
          color: '#fff',
          border: 'none',
          borderRadius: '50%',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          cursor: capturing ? 'wait' : 'pointer',
          opacity: capturing ? 0.7 : 1,
        }}
      >
        <FeedbackIcon />
      </button>
      <FeedbackModal
        isOpen={open}
        onClose={handleClose}
        url={url}
        screenshot={screenshot}
        screenshotError={screenshotError}
      />
    </>
  );
};

export default FeedbackButton;
