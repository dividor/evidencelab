import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { BriefFactCheckEvidence, BriefFactCheckMark } from '../../types/testing';
import { ClaimAssessment, ClaimReference, EvidenceGaps } from './ClaimAssessment';
import type { FactEvidenceState } from './useBriefFactCheck';

type OpenSource = (source: BriefFactCheckEvidence) => void;

function SourceExcerpt({ source, onOpen }: { source: BriefFactCheckEvidence; onOpen?: OpenSource }) {
  const excerpt = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const el = excerpt.current!;
    if (expanded) return;
    const measure = () => setClipped(el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [expanded, source]);
  return <ClaimReference number={source.citation} title={source.title} page={source.page}>
    {!source.quoted && <p>The judge quoted nothing from this excerpt.</p>}
    <div ref={excerpt} className={`brief-fact-excerpt${expanded ? ' expanded' : ''}`}>
      {source.segments.map((segment, i) => segment.highlighted
        ? <mark key={i} className="brief-fact-quote">{segment.text}</mark>
        : <React.Fragment key={i}>{segment.text}</React.Fragment>)}
    </div>
    <div className="brief-claim-source-actions">
      {(clipped || expanded) && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? 'See less' : 'See more'}
      </button>}
      {onOpen && <button type="button" onClick={() => onOpen(source)}>Open source</button>}
    </div>
  </ClaimReference>;
}

function Sources({ evidence, onOpen }: { evidence: FactEvidenceState | null; onOpen?: OpenSource }) {
  if (!evidence || evidence.status === 'loading') return <p role="status">Loading the cited excerpts…</p>;
  if (evidence.status === 'failed') return <p role="alert">The cited excerpts could not be loaded.</p>;
  if (!evidence.blocks.length) return <p>No excerpt was stored for this claim.</p>;
  return <>{evidence.blocks.map((source, i) => <SourceExcerpt key={i} source={source} onOpen={onOpen} />)}</>;
}

export function BriefClaimDialog({ mark, evidence, onClose, onOpenSource }: {
  mark: BriefFactCheckMark; evidence: FactEvidenceState | null; onClose: () => void; onOpenSource?: OpenSource;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const el = dialog.current!;
    el.showModal();
    return () => el.close();
  }, []);
  return createPortal(
    <dialog ref={dialog} className="brief-modal brief-claim-dialog"
      aria-label={mark.grade ? `Claim ${mark.grade.claim}` : 'Citation check verdict'}
      onCancel={onClose} onClick={event => {
        if (event.target !== event.currentTarget) return;
        const r = event.currentTarget.getBoundingClientRect();
        if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) onClose();
      }}>
      <button type="button" className="brief-modal-close brief-claim-close" aria-label="Close claim" onClick={onClose}>×</button>
      {mark.grade && mark.claim_text != null ? (
        <ClaimAssessment number={mark.grade.claim} text={mark.claim_text} grade={mark.grade} showPass={false} />
      ) : <>
        <div className="testing-claim-heading"><strong>{mark.verdict_label}</strong>
          {mark.confidence != null && <span>{Math.round(mark.confidence * 100)}% confidence</span>}
          <span>Judged against [{mark.citations}]</span>
        </div>
        <p>{mark.passage}</p>
        <p><strong>Judge assessment</strong> {mark.explanation}</p>
        <EvidenceGaps verdict={mark.verdict} unmet={mark.problems} />
      </>}
      {mark.quote_not_in_source && <p>A quote the judge gave could not be found in the source.</p>}
      <h3>Sources</h3>
      <Sources evidence={evidence} onOpen={onOpenSource && (source => { onClose(); onOpenSource(source); })} />
    </dialog>, document.body,
  );
}
