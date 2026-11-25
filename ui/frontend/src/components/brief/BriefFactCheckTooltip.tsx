import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { BriefFactCheckEvidence } from '../../types/testing';
import type { BriefFactCheckMark } from '../../types/testing';
import type {
  FactAcceptanceControls,
  FactEvidenceState,
  FactMarkHover,
} from './useBriefFactCheck';

// The card for the highlighted passage under the pointer: the verdict as a
// badge, the judge's reason, then the evidence: each cited excerpt as the
// judge read it, with the parts it quoted highlighted. Rendered into the
// body so it floats over everything, placed above the passage when there is
// no room below, and kept open while the pointer is on it so its excerpts
// can be scrolled and its sources opened.
//
// Those who may (the brief's owner and administrators) can overrule the
// judge from the card: "Accept citation" opens an optional comment and Save.
// An accepted passage says who accepted it, when and why above the judge's
// reasoning, and the acceptance can be withdrawn.

const CARD_WIDTH = 440;
const MARGIN = 8;

// Where the card hangs: below the passage (from `top`) when it fits there or
// there is more room below than above, else above it (from `bottom`), never
// taller than the room on that side.
interface Placement {
  top?: number;
  bottom?: number;
  maxHeight: number;
}

const placement = (rect: FactMarkHover['rect'], height: number): Placement => {
  const roomBelow = window.innerHeight - rect.bottom - 2 * MARGIN;
  const roomAbove = rect.top - 2 * MARGIN;
  if (height <= roomBelow || roomBelow >= roomAbove) {
    return { top: rect.bottom + MARGIN, maxHeight: Math.max(roomBelow, 120) };
  }
  return {
    bottom: window.innerHeight - rect.top + MARGIN,
    maxHeight: Math.max(roomAbove, 120),
  };
};

interface BriefFactCheckTooltipProps {
  hover: FactMarkHover | null;
  evidence: FactEvidenceState | null;
  onEnter?: () => void;
  onLeave?: () => void;
  // Opens a cited source in the app's document preview.
  onOpenSource?: (source: BriefFactCheckEvidence) => void;
  // Null when this user may not accept citations.
  acceptance?: FactAcceptanceControls | null;
}

const failure = (err: any, fallback: string): string => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

// The comment and Save, open after "Accept citation" was clicked.
const AcceptanceForm: React.FC<{
  mark: BriefFactCheckMark;
  acceptance: FactAcceptanceControls;
  onClose: () => void;
}> = ({ mark, acceptance, onClose }) => {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The card stays on this passage while the comment is being written.
  const { setPinned } = acceptance;
  useEffect(() => {
    setPinned(true);
    return () => setPinned(false);
  }, [setPinned]);
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await acceptance.accept(mark.passage_id, comment);
      onClose();
    } catch (err) {
      setError(failure(err, 'The acceptance could not be saved.'));
      setBusy(false);
    }
  };
  return (
    <div className="brief-fact-accept-form">
      <label className="brief-fact-accept-label" htmlFor={`brief-fact-comment-${mark.passage_id}`}>
        Comment (optional)
      </label>
      <textarea
        id={`brief-fact-comment-${mark.passage_id}`}
        className="brief-fact-accept-comment"
        rows={3}
        maxLength={acceptance.commentMaxLength}
        placeholder="Why the citation holds, for example what you checked in the source"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        autoFocus
      />
      {error && <div className="brief-fact-accept-error">{error}</div>}
      <div className="brief-fact-accept-actions">
        <button type="button" className="brief-btn brief-btn-primary" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="brief-btn brief-btn-secondary" onClick={onClose} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
};

// What a person decided about the passage: who accepted its citation and
// why, with a way to withdraw that; or, for those who may, the way to accept.
const Acceptance: React.FC<{
  mark: BriefFactCheckMark;
  acceptance: FactAcceptanceControls | null;
}> = ({ mark, acceptance }) => {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const withdraw = async () => {
    if (!acceptance) return;
    setBusy(true);
    setError('');
    try {
      await acceptance.withdraw(mark.passage_id);
    } catch (err) {
      setError(failure(err, 'The acceptance could not be withdrawn.'));
    } finally {
      setBusy(false);
    }
  };
  if (mark.accepted) {
    return (
      <div className="brief-fact-accepted">
        <div className="brief-fact-accepted-who">{mark.accepted_label}</div>
        {mark.accepted_comment && <p className="brief-fact-accepted-comment">{mark.accepted_comment}</p>}
        {error && <div className="brief-fact-accept-error">{error}</div>}
        {acceptance && (
          <button type="button" className="brief-fact-evidence-open" onClick={withdraw} disabled={busy}>
            Withdraw acceptance
          </button>
        )}
      </div>
    );
  }
  if (!acceptance) return null;
  if (editing) {
    return <AcceptanceForm mark={mark} acceptance={acceptance} onClose={() => setEditing(false)} />;
  }
  return (
    <div className="brief-fact-accept">
      <button
        type="button"
        className="brief-btn brief-btn-secondary"
        onClick={() => setEditing(true)}
        title="Record that you checked this citation yourself and accept it"
      >
        Accept citation
      </button>
    </div>
  );
};

// Scroll an excerpt to its first quoted run, so the evidence is in view.
const ExcerptText: React.FC<{ source: BriefFactCheckEvidence }> = ({ source }) => {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const box = ref.current;
    const first = box?.querySelector<HTMLElement>('.brief-fact-quote');
    if (box && first) box.scrollTop = Math.max(0, first.offsetTop - box.offsetTop - 12);
  }, [source]);
  return (
    <div ref={ref} className="brief-fact-excerpt">
      {source.segments.map((segment, i) =>
        segment.highlighted ? (
          <mark key={i} className="brief-fact-quote">
            {segment.text}
          </mark>
        ) : (
          <React.Fragment key={i}>{segment.text}</React.Fragment>
        ),
      )}
    </div>
  );
};

const EvidenceBlock: React.FC<{
  source: BriefFactCheckEvidence;
  onOpenSource?: (source: BriefFactCheckEvidence) => void;
}> = ({ source, onOpenSource }) => (
  <section className={`brief-fact-evidence${source.quoted ? '' : ' brief-fact-evidence-unquoted'}`}>
    <div className="brief-fact-evidence-head">
      <span className="brief-fact-evidence-kicker">Evidence in source</span>
      <span className="brief-fact-evidence-label" title={source.section || undefined}>
        {source.label}
      </span>
      {onOpenSource && (
        <button
          type="button"
          className="brief-fact-evidence-open"
          onClick={() => onOpenSource(source)}
          title="Open this excerpt in the document preview"
        >
          Open source
        </button>
      )}
    </div>
    {!source.quoted && (
      <div className="brief-fact-evidence-note">The judge quoted nothing from this excerpt.</div>
    )}
    <ExcerptText source={source} />
  </section>
);

const Evidence: React.FC<{
  evidence: FactEvidenceState | null;
  onOpenSource?: (source: BriefFactCheckEvidence) => void;
}> = ({ evidence, onOpenSource }) => {
  if (!evidence || evidence.status === 'loading') {
    return <div className="brief-fact-evidence-status">Loading the cited excerpts…</div>;
  }
  if (evidence.status === 'failed') {
    return (
      <div className="brief-fact-evidence-status brief-fact-evidence-failed">
        The cited excerpts could not be loaded.
      </div>
    );
  }
  if (!evidence.blocks.length) {
    return <div className="brief-fact-evidence-status">No excerpt was stored for this passage.</div>;
  }
  return (
    <>
      {evidence.blocks.map((source, i) => (
        <EvidenceBlock key={`${source.citation}-${i}`} source={source} onOpenSource={onOpenSource} />
      ))}
    </>
  );
};

export const BriefFactCheckTooltip: React.FC<BriefFactCheckTooltipProps> = ({
  hover,
  evidence,
  onEnter,
  onLeave,
  onOpenSource,
  acceptance = null,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  // Placed once per passage, anchored to the edge it hangs from: the card
  // grows as its evidence arrives, and moving it under a resting pointer
  // would close it.
  const [place, setPlace] = useState<Placement | null>(null);
  const placedFor = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (!hover || !ref.current) {
      setPlace(null);
      placedFor.current = null;
      return;
    }
    if (placedFor.current === hover.mark.passage_id) return;
    placedFor.current = hover.mark.passage_id;
    setPlace(placement(hover.rect, ref.current.offsetHeight));
  }, [hover]);
  if (!hover) return null;
  const { mark, rect } = hover;
  const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - CARD_WIDTH - 2 * MARGIN));
  return createPortal(
    <div
      ref={ref}
      className="brief-fact-card"
      role="note"
      aria-label="Citation check verdict"
      style={{
        ...(place ?? { top: rect.bottom + MARGIN }),
        left,
        visibility: place === null ? 'hidden' : 'visible',
      }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <div className="brief-fact-card-head">
        {mark.accepted && (
          <span className={`brief-fact-badge brief-fact-mark-${mark.highlight}`}>{mark.highlight_label}</span>
        )}
        <span className={`brief-fact-badge brief-fact-mark-${mark.verdict}`}>{mark.verdict_label}</span>
        {mark.confidence != null && (
          <span className="brief-fact-card-meta">{Math.round(mark.confidence * 100)}% confidence</span>
        )}
        <span className="brief-fact-card-meta">Judged against [{mark.citations}]</span>
      </div>
      <Acceptance key={mark.passage_id} mark={mark} acceptance={acceptance} />
      <p className="brief-fact-card-reason">{mark.explanation}</p>
      {mark.quote_not_in_source && (
        <div className="brief-fact-card-warning">
          A quote the judge gave was not found in the source; read the evidence with care.
        </div>
      )}
      <Evidence evidence={evidence} onOpenSource={onOpenSource} />
    </div>,
    document.body,
  );
};
